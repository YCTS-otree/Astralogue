"""Bounded, resumable BWIKI acquisition. No runtime or automatic startup hooks."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import random
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from email.utils import parsedate_to_datetime

from astralogue.http import verified_opener
from astralogue.model import canonical, load_json, file_hash

BASE = 'https://wiki.biligame.com'
CHAPTER = '今天是昨天的明天'
TITLES = ('混乱行至深处', '漩涡止于中心', '宇宙安宁片刻', '阴影从未离去', '模拟宇宙•始发测试', '旅途正在继续', '星间流浪')
AGENT = 'Astralogue-BwikiPilot/1.12 (bounded offline narrative research)'


@contextmanager
def single_instance(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
            try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise ValueError('Pilot worker already running') from None
        else:
            import fcntl
            try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError: raise ValueError('Pilot worker already running') from None
        yield
    finally:
        f.close()  # OS releases the lock after a crash as well.


def atomic(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.part')
    with temp.open('wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    if hashlib.sha256(temp.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
        raise ValueError('Cache write hash mismatch')
    temp.replace(path)


class Pilot:
    def __init__(self, root: Path, interval: float = 120, daily_budget: int = 12):
        if interval < 120 or not 1 <= daily_budget <= 24:
            raise ValueError('Minimum interval is 120s; daily budget must be 1..24')
        self.root = root.resolve(); self.root.mkdir(parents=True, exist_ok=True)
        self.interval = interval; self.budget = daily_budget
        self.db = sqlite3.connect(self.root / 'queue.sqlite', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS pages(title TEXT PRIMARY KEY, chapter TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'PENDING', page_id INTEGER, revision_id INTEGER,
          url TEXT, sha256 TEXT, cache TEXT, fetched_at TEXT, parsed TEXT,
          attempts INTEGER NOT NULL DEFAULT 0, error TEXT, next_at REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(at REAL NOT NULL, url TEXT NOT NULL, outcome TEXT);
        ''')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', ('state', 'stopped'))
            self.db.execute('INSERT OR IGNORE INTO pages(title,chapter) VALUES(?,?)', (CHAPTER, '100001'))

    def close(self): self.db.close()

    def state(self, value=None):
        if value is not None:
            with self.db: self.db.execute('UPDATE settings SET value=? WHERE key=?', (value, 'state'))
        return self.db.execute('SELECT value FROM settings WHERE key=?', ('state',)).fetchone()[0]

    def status(self):
        return {'state': self.state(), 'settings':dict(self.db.execute('SELECT key,value FROM settings')), 'requests': self.db.execute("SELECT COUNT(*) FROM requests WHERE outcome != 'completed'").fetchone()[0],
                'pages': [dict(r) for r in self.db.execute('SELECT * FROM pages ORDER BY rowid')]}

    def cache_path(self, title):
        return self.root / 'cache' / (hashlib.sha256(title.encode()).hexdigest() + '.json')

    def import_page(self, path: Path):
        raw = path.read_bytes(); p = json.loads(raw)['parse']; title = p['title']
        if title not in (CHAPTER, *TITLES) and not self.db.execute('SELECT 1 FROM pages WHERE title=?',(title,)).fetchone(): raise ValueError('Page outside confirmed queue scope')
        if not isinstance(p['pageid'], int) or not isinstance(p['revid'], int) or not isinstance(p['wikitext']['*'], str):
            raise ValueError('Incomplete MediaWiki snapshot')
        dest = self.cache_path(title); atomic(dest, raw)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO pages(title,chapter) VALUES(?,?)', (title, '100001'))
            self.db.execute('UPDATE pages SET status=?,page_id=?,revision_id=?,url=?,sha256=?,cache=?,fetched_at=?,error=NULL WHERE title=?',
                ('FETCHED', p['pageid'], p['revid'], BASE+'/sr/'+urllib.parse.quote(title), hashlib.sha256(raw).hexdigest(),
                 str(dest.relative_to(self.root)), datetime.now(timezone.utc).isoformat(), title))
        return title

    def recover(self):
        # Only call while holding the worker lock; an owner cannot still be fetching.
        for r in list(self.db.execute('SELECT * FROM pages')):
            path = self.cache_path(r['title'])
            if r['sha256'] and (not path.exists() or file_hash(path) != r['sha256']):
                with self.db: self.db.execute('UPDATE pages SET status=?,error=? WHERE title=?', ('FAILED', 'Cache integrity failure; manual repair required', r['title']))
            elif r['status'] == 'FETCHING':
                if path.exists(): self.import_page(path)
                else:
                    with self.db: self.db.execute('UPDATE pages SET status=? WHERE title=?', ('PENDING', r['title']))

    def parse_cached(self):
        from .bwiki import parse_page
        from .scenes import classify_page
        for r in list(self.db.execute("SELECT * FROM pages WHERE status IN ('FETCHED','PARSED')")):
            path = self.root / r['cache']
            try:
                if file_hash(path) != r['sha256']: raise ValueError('Snapshot hash mismatch')
                data = load_json(path); text = data['parse']['wikitext']['*']
                if r['title'] == '开拓任务':
                    from .pilot_catalogue import mission_links
                    found=mission_links(data['parse'].get('text',{}).get('*',''))
                    if not found:raise ValueError('No recognized mission catalogue structure')
                    with self.db:
                        for title,chapter in found:
                            self.db.execute('INSERT OR IGNORE INTO pages(title,chapter) VALUES(?,?)',(title,chapter))
                    result={'confirmed_missions':found,'target_version':'4.5','version_verified':False}
                elif r['title'] == CHAPTER:
                    # Titles must actually occur as Wiki links in the chapter index.
                    import re
                    links = {m.group(1).split('|')[0].split('#')[0].strip() for m in re.finditer(r'\[\[([^\]]+)\]\]', text)}
                    from html.parser import HTMLParser
                    class Links(HTMLParser):
                        def handle_starttag(self, tag, attrs):
                            a = dict(attrs)
                            if tag == 'a' and a.get('href','').startswith('/sr/'):
                                links.add(urllib.parse.unquote(a['href'][4:]).replace('_',' '))
                    Links().feed(data['parse'].get('text',{}).get('*',''))
                    with self.db:
                        for title in TITLES:
                            if title in links: self.db.execute('INSERT OR IGNORE INTO pages(title,chapter) VALUES(?,?)', (title, '100001'))
                    result = {'confirmed_titles': [t for t in TITLES if t in links], 'missing_titles': [t for t in TITLES if t not in links]}
                    if result['missing_titles']: raise ValueError('Chapter index does not confirm all requested titles: '+str(result))
                else:
                    try:result = classify_page(parse_page(path))
                    except ValueError as e:
                        result={'title':r['title'],'unparsed_structure':str(e),'raw_cache':r['cache'],'not_executable':True}
                    import re
                    version=re.search(r'\|所属版本\s*=\s*([0-9]+\.[0-9]+)',text)
                    result['declared_game_version']=version[1] if version else None
                    result['within_target_version']=bool(version and tuple(map(int,version[1].split('.'))) <= (4,5))
                out = path.with_suffix('.parsed.json'); atomic(out, (canonical(result)+'\n').encode())
                with self.db: self.db.execute('UPDATE pages SET status=?,parsed=?,error=NULL WHERE title=?', ('VALIDATED', str(out.relative_to(self.root)), r['title']))
            except (ValueError, KeyError, OSError) as e:
                with self.db: self.db.execute('UPDATE pages SET status=?,error=? WHERE title=?', ('FAILED', 'Local parse: '+str(e), r['title']))

    def due(self, now):
        if not self.work_window(now):return False
        configured=self.db.execute("SELECT value FROM settings WHERE key='daily_budget'").fetchone()
        if configured:self.budget=int(configured[0])
        rows = list(self.db.execute('SELECT at,outcome FROM requests ORDER BY at DESC'))
        today = datetime.fromtimestamp(now, timezone.utc).date()
        count = sum(datetime.fromtimestamp(r['at'], timezone.utc).date() == today and r['outcome'] != 'completed' for r in rows)
        if count >= self.budget: return False
        return not rows or now >= rows[0]['at'] + self.interval

    def work_window(self, now):
        enabled=self.db.execute("SELECT value FROM settings WHERE key='work_schedule'").fetchone()
        if not enabled:return True
        local=datetime.fromtimestamp(now,timezone(timedelta(hours=8)))
        if not (8<=local.hour<12 or 14<=local.hour<22):return False
        row=self.db.execute("SELECT value FROM settings WHERE key='work_cycle'").fetchone()
        cycle=json.loads(row[0]) if row else {}
        if now<cycle.get('rest_until',0):return False
        if now<cycle.get('work_until',0):
            if 'quota' not in cycle:
                cycle.update(quota=random.randint(4,5),pages=0)
                with self.db:self.db.execute("INSERT OR REPLACE INTO settings VALUES('work_cycle',?)",(canonical(cycle),))
            return cycle.get('pages',0)<cycle['quota']
        if cycle.get('work_until',0)>cycle.get('rest_until',0):
            cycle={'rest_until':cycle['work_until']+random.randint(600,1200)}
            allowed=False
        else:
            cycle={'work_until':now+random.randint(600,900),'quota':random.randint(4,5),'pages':0}
            allowed=True
        with self.db:self.db.execute("INSERT OR REPLACE INTO settings VALUES('work_cycle',?)",(canonical(cycle),))
        if not allowed and now>=cycle['rest_until']:return self.work_window(now)
        return allowed

    def count_cycle_page(self):
        row=self.db.execute("SELECT value FROM settings WHERE key='work_cycle'").fetchone()
        if row:
            cycle=json.loads(row[0]);cycle['pages']=cycle.get('pages',0)+1
            with self.db:self.db.execute("INSERT OR REPLACE INTO settings VALUES('work_cycle',?)",(canonical(cycle),))

    def tick(self, proxy=None, now=None):
        now = time.time() if now is None else now
        self.parse_cached()
        if self.state() != 'running': return False
        row = self.db.execute("SELECT * FROM pages WHERE status='PENDING' AND next_at<=? ORDER BY rowid LIMIT 1", (now,)).fetchone()
        if row is None:
            if not self.db.execute("SELECT 1 FROM pages WHERE status IN ('PENDING','FETCHING')").fetchone():
                target=self.db.execute("SELECT value FROM settings WHERE key='target_version'").fetchone()
                if target:
                    versions=[]
                    for page in self.status()['pages']:
                        if page['parsed']:
                            versions.append(load_json(self.root/page['parsed']).get('declared_game_version'))
                    if '4.5' in versions and all(p['status']=='VALIDATED' for p in self.status()['pages']):
                        self.state('completed');return False
                    # Check for new catalogue content once a day while waiting
                    # for the requested version; never claim future coverage.
                    with self.db:self.db.execute("UPDATE pages SET status='PENDING',next_at=? WHERE title='开拓任务'",(now+86400,))
                else:self.state('completed' if all(r['status']=='VALIDATED' for r in self.status()['pages']) else 'paused')
            return False
        if not self.due(now): return False
        robots = self.root / 'robots.txt'
        if not robots.exists() or now - robots.stat().st_mtime > 86400:
            url = BASE+'/robots.txt'; title = None
        else:
            title = row['title']; url = BASE+'/sr/api.php?'+urllib.parse.urlencode({'action':'parse','page':title,'prop':'wikitext|text|revid','format':'json'})
            rules = urllib.robotparser.RobotFileParser(); rules.parse(robots.read_text(encoding='utf8').splitlines())
            if not rules.can_fetch(AGENT, url): self.state('paused'); return False
        with self.db:
            self.db.execute('INSERT INTO requests VALUES(?,?,?)', (now, url, 'started'))
            if title: self.db.execute("UPDATE pages SET status='FETCHING',attempts=attempts+1 WHERE title=?", (title,))
        try:
            req = urllib.request.Request(url, headers={'User-Agent':AGENT})
            with verified_opener(proxy).open(req, timeout=30) as response:
                raw = response.read(24*1024*1024+1)
                if len(raw)>24*1024*1024: raise ValueError('Page exceeds size budget')
                if urllib.parse.urlparse(response.url).hostname != 'wiki.biligame.com': raise ValueError('Unexpected redirect host')
            if title:
                data = json.loads(raw)
                if data.get('parse',{}).get('title') != title: raise ValueError('API page title mismatch or missing page')
                dest = self.cache_path(title); atomic(dest, raw); self.import_page(dest)
                self.count_cycle_page()
            else:
                if b'User-agent:' not in raw and b'user-agent:' not in raw: raise ValueError('Unrecognized robots response')
                atomic(robots, raw)
            with self.db:
                self.db.execute('UPDATE requests SET outcome=? WHERE at=?', ('ok',now))
                # The interval starts at response completion, not request start.
                self.db.execute('INSERT INTO requests VALUES(?,?,?)', (max(now,time.time()),url,'completed'))
            return True
        except (OSError, ValueError) as e:
            attempts = row['attempts']+1; delay = self.interval * 2**attempts
            if isinstance(e, urllib.error.HTTPError):
                retry = e.headers.get('Retry-After')
                if retry:
                    try: delay = max(delay,float(retry))
                    except ValueError:
                        try: delay = max(delay,parsedate_to_datetime(retry).timestamp()-now)
                        except (ValueError,TypeError): pass
                if e.code in (403,429) or e.code>=500: self.state('paused')
            if not title: self.state('paused')
            with self.db:
                self.db.execute('UPDATE requests SET outcome=? WHERE at=?', (str(e),now))
                if title: self.db.execute('UPDATE pages SET status=?,error=?,next_at=? WHERE title=?', ('FAILED' if attempts>=3 else 'PENDING',str(e),max(now,time.time())+delay,title))
            return False

    def run(self, proxy=None):
        with single_instance(self.root/'worker.lock'):
            self.recover()
            while self.state() == 'running':
                self.tick(proxy)
                time.sleep(1)  # Local control responsiveness; network is governed by due().
