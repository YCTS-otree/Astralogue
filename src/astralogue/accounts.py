"""Local accounts with one canonical, pack-bound save per account."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import unicodedata
import uuid

from astralogue.model import canonical, load_json

DEFAULT_ACCOUNTS = Path('saves/accounts')
DEFAULT_PLAYER_PACK = Path('data/packs/prologue-player.storypack')
# Public bootstrap account: only the salted verifier is kept in source.
BOOTSTRAP_SALT = '9a1f97b123ce6bb5fa027204b8c9e4ff'
BOOTSTRAP_HASH = 'efb166077aa473b9ff81bc556ec2295d4eaa5f5bc0d46d31329345671f897def'


@dataclass(frozen=True)
class Account:
    id: str
    name: str


def username(value: str) -> tuple[str, str]:
    name = unicodedata.normalize('NFKC', value).strip()
    if not name or len(name) > 32 or any(unicodedata.category(c).startswith('C') for c in name):
        raise ValueError('账号名需为 1–32 个字符，不能含控制字符')
    return name, name.casefold()


def password_hash(password: str, salt: str) -> str:
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        raise ValueError('密码需为 1–128 个字符')
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf8'), bytes.fromhex(salt), 120000).hex()


class AccountStore:
    """A single row owns a single save, updated transactionally, never a slot list."""

    def __init__(self, directory: Path = DEFAULT_ACCOUNTS):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.directory/'accounts.sqlite', timeout=10)
        self.con.row_factory = sqlite3.Row
        version=self.con.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0,1}:
            self.con.close();raise ValueError('账号数据库版本不受支持')
        self.con.execute('''CREATE TABLE IF NOT EXISTS accounts(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, login TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            pack_id TEXT, save_json TEXT, revision INTEGER NOT NULL DEFAULT 0)''')
        self.con.commit()
        self.con.execute('PRAGMA user_version=1')
        with self.con:
            self.con.execute('INSERT OR IGNORE INTO accounts(id,name,login,salt,password_hash) VALUES(?,?,?,?,?)',
                             (uuid.uuid4().hex,'0','0',BOOTSTRAP_SALT,BOOTSTRAP_HASH))
            self.con.execute('CREATE TABLE IF NOT EXISTS account_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            if not self.con.execute("SELECT 1 FROM account_settings WHERE key='bootstrap_zero_v1'").fetchone():
                # Existing databases may already contain a user named 0. Apply
                # the explicitly requested default credential once, preserving
                # its identity, progress, revision and all other accounts.
                self.con.execute("UPDATE accounts SET salt=?,password_hash=? WHERE login='0'",(BOOTSTRAP_SALT,BOOTSTRAP_HASH))
                self.con.execute("INSERT INTO account_settings VALUES('bootstrap_zero_v1','applied')")

    def __enter__(self): return self
    def __exit__(self, *args): self.con.close()

    def register(self, name: str, password: str) -> Account:
        display, login = username(name); salt = secrets.token_hex(16)
        encoded = password_hash(password, salt); aid = uuid.uuid4().hex
        try:
            with self.con:
                self.con.execute('INSERT INTO accounts(id,name,login,salt,password_hash) VALUES(?,?,?,?,?)',
                                 (aid, display, login, salt, encoded))
        except sqlite3.IntegrityError as ex:
            raise ValueError('账号已存在，请登录') from ex
        return Account(aid, display)

    def login(self, name: str, password: str) -> Account:
        _, key = username(name)
        row = self.con.execute('SELECT id,name,salt,password_hash FROM accounts WHERE login=?', (key,)).fetchone()
        if row is None or not hmac.compare_digest(password_hash(password, row['salt']), row['password_hash']):
            raise ValueError('账号或密码错误')
        return Account(row['id'], row['name'])

    def progress(self, account: Account) -> dict:
        row = self.con.execute('SELECT pack_id,save_json,revision FROM accounts WHERE id=?', (account.id,)).fetchone()
        if row is None: raise ValueError('账号不存在')
        return dict(row)

    def reset_progress(self, account: Account):
        """Explicit reset, while holding the account lock; invalidates stale writers."""
        with self.con:
            self.con.execute('UPDATE accounts SET pack_id=NULL,save_json=NULL,revision=revision+1 WHERE id=?',(account.id,))

    @contextmanager
    def lock(self, account: Account):
        """OS lock survives pauses and is automatically released after a crash."""
        if not re.fullmatch('[a-f0-9]{32}', account.id): raise ValueError('账号标识无效')
        folder = self.directory/'locks'; folder.mkdir(exist_ok=True)
        with (folder/(account.id+'.lock')).open('a+b') as handle:
            if handle.tell() == 0: handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as ex:
                raise ValueError('该账号已在另一个窗口中打开，请先退出') from ex
            try: yield
            finally:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def commit(self, account: Account, payload: dict, revision: int) -> int:
        if payload.get('account_id') != account.id: raise ValueError('存档不属于当前账号')
        encoded = canonical(payload)
        with self.con:
            row = self.progress(account)
            if row['revision'] != revision: raise ValueError('进度已被其他会话更新，请重新登录')
            if row['pack_id'] and row['pack_id'] != payload['pack_id']:
                raise ValueError('该账号已绑定其他版本的剧情包，不能另开或重置存档')
            if row['save_json']:
                before = json.loads(row['save_json'])['state']; after = payload['state']
                old_choices = before['choices']
                if after['choices'][:len(old_choices)] != old_choices:
                    raise ValueError('账号进度不能回档或改写已确认选择')
                old = before['variables'].get('player_profile', {}); new = after['variables'].get('player_profile', {})
                for flag, fields in [('avatar_confirmed', ['avatar_id','avatar_name']), ('name_confirmed', ['nickname'])]:
                    if old.get(flag) and (not new.get(flag) or any(old.get(k) != new.get(k) for k in fields)):
                        raise ValueError('账号已经确认的载体和代号不能更改')
            if row['save_json'] == encoded: return revision
            changed = self.con.execute('UPDATE accounts SET pack_id=?,save_json=?,revision=revision+1 WHERE id=? AND revision=?',
                                       (payload['pack_id'], encoded, account.id, revision))
            if changed.rowcount != 1: raise ValueError('进度更新冲突，请重新登录')
        return revision + 1


class AccountProgress:
    """Bridge existing save serialization to the account's single SQLite record."""

    def __init__(self, store: AccountStore, account: Account, pack):
        self.store = store; self.account = account; self.pack = pack
        row = store.progress(account); self.revision = row['revision']; self.saved = row['save_json']
        if row['pack_id'] and row['pack_id'] != pack.metadata['pack_id']:
            raise ValueError('账号进度与当前剧情包版本不兼容；保留原进度，需要显式升级迁移')

    def open(self, seed: Path | None = None):
        from astralogue.arcs.session import session, load_session
        if self.saved:
            if seed is not None: raise ValueError('账号已有进度，不能再次导入或替换存档')
            data = json.loads(self.saved)
            if data.get('account_id') != self.account.id: raise ValueError('账号存档归属错误')
            with tempfile.TemporaryDirectory(dir=self.store.directory) as folder:
                path = Path(folder)/'progress.json'; path.write_text(self.saved, encoding='utf8')
                return load_session(self.pack, path)
        if seed is not None:
            if load_json(seed).get('account_id'):raise ValueError('不能导入其他账号的存档')
            rt=load_session(self.pack,seed);self.save(rt);return rt
        mid = self.pack.metadata.get('narrative', {}).get('entries', {}).get('reader')
        if not mid:
            missions = self.pack.missions()
            if len(missions) != 1: raise ValueError('此剧情包缺少唯一的阅读入口')
            mid = missions[0]['id']
        rt = session(self.pack, mid); self.save(rt)
        return rt

    def save(self, rt):
        if rt.pack.metadata['pack_id'] != self.pack.metadata['pack_id']: raise ValueError('账号剧情包不匹配')
        with tempfile.TemporaryDirectory(dir=self.store.directory) as folder:
            path = Path(folder)/'progress.json'; rt.save(path); data = load_json(path)
        data['account_id'] = self.account.id
        self.revision = self.store.commit(self.account, data, self.revision)
        self.saved = canonical(data)


def read_password(prompt: str) -> str:
    from astralogue.cli import console
    if sys.stdin.isatty():return console.input(prompt,password=True)
    # Redirected input has no terminal echo to disable. Read without echoing
    # credentials or emitting getpass's terminal-control warnings into logs.
    console.print(prompt,end='',markup=False)
    line=sys.stdin.readline()
    if line=='':raise EOFError
    return line.rstrip('\r\n')


def launch(pack_path: Path = DEFAULT_PLAYER_PACK, directory: Path = DEFAULT_ACCOUNTS, debug: bool = False, seed: Path | None = None):
    from astralogue.cli import console, errors, interact, debug_enabled
    from astralogue.storypack import StoryPack
    debug = debug_enabled(debug)
    with errors(), AccountStore(directory) as store:
        console.print('Astralogue · 星轨叙事', markup=False)
        while True:
            console.print('1. 登录\n2. 注册\n0. 退出', markup=False)
            try:
                choice = console.input('请选择 > ').strip()
                if choice == '0': return
                if choice not in {'1','2'}: console.print('请输入 1、2 或 0。'); continue
                name = console.input('账号 > ')
                password = read_password('密码 > ')
                if choice == '2':
                    confirmation = read_password('确认密码 > ')
                    if confirmation != password: raise ValueError('两次密码不一致')
                    account = store.register(name, password)
                else: account = store.login(name, password)
                del password
                console.print('欢迎，'+account.name, markup=False)
                with store.lock(account), StoryPack(pack_path) as pack:
                    selected=None
                    if account.name=='0' and pack.metadata.get('story_arcs'):
                        choices=[]
                        console.print('【章节 / 小节选择】\n0. 继续现有进度',markup=False)
                        for mid,arc in pack.metadata['story_arcs'].items():
                            for boundary in arc['task_boundaries']:
                                choices.append((mid,boundary))
                                console.print(f"{len(choices)}. {arc['plan']['title']} · {boundary['title']}",markup=False)
                        value=console.input('请选择 > ').strip()
                        if not value.isdecimal() or not 0<=int(value)<=len(choices):raise ValueError('请选择有效章节')
                        if int(value):selected=choices[int(value)-1]
                    if selected:
                        from astralogue.arcs.session import ArcSession
                        old=store.progress(account)['save_json']
                        rt=ArcSession(pack,selected[0]);rt.state.node=selected[1]['entry']
                        if old:
                            previous=json.loads(old)
                            profile=previous['state']['variables'].get('player_profile')
                            if profile:rt.state.variables['player_profile']=profile
                        if rt.avatars and not rt.profile.name_confirmed and selected[1]['task']>0:
                            rt.profile_migration=True;rt.state.variables['profile_migration_required']=True
                        rt.migrations.append({'manual_chapter_selection':{'mission':selected[0],'entry':selected[1]['entry']},
                                              'policy':'explicit_user_navigation; not a game control edge'})
                        store.reset_progress(account)
                    progress = AccountProgress(store, account, pack)
                    if selected:
                        if seed is not None:raise ValueError('章节选择不能同时导入存档')
                        progress.save(rt)
                    else:rt = progress.open(seed)
                    seed = None
                    result = interact(rt, directory/'unused', directory/'unused', debug, account=progress)
                if result == 'eof': return
            except (EOFError, KeyboardInterrupt): return
            except (ValueError, OSError, sqlite3.Error) as ex:
                console.print(str(ex), style='yellow', markup=False)
