from copy import deepcopy
from pathlib import Path
import json

import pytest
from typer.testing import CliRunner

from astralogue.accounts import AccountStore, AccountProgress
from astralogue.cli import app
from astralogue.model import load_json
from astralogue.runtime import DialogueEvent, ChoiceEvent, EndEvent
from astralogue.storypack import StoryPack


@pytest.fixture(autouse=True)
def isolate_generic_account_infrastructure(monkeypatch):
    # Synthetic non-HSR packs test storage/locking separately from availability.
    from astralogue.accounts import allowed_scope
    monkeypatch.setattr('astralogue.accounts.allowed_scope',lambda p,a:allowed_scope(p,a) if p.metadata.get('story_arcs') else None)


def test_bootstrap_account_and_explicit_reset(pack_path,tmp_path):
    with AccountStore(tmp_path) as store,StoryPack(pack_path) as pack:
        account=store.login('0',bytes(range(48,56)).decode())
        progress=AccountProgress(store,account,pack);rt=progress.open();rt.next();progress.save(rt)
        rev=store.progress(account)['revision']
        with store.lock(account):store.reset_progress(account)
        assert store.progress(account)['save_json'] is None and store.progress(account)['pack_id'] is None
        assert store.progress(account)['revision']>rev
        assert AccountProgress(store,account,pack).open().state.node=='a'


def test_existing_zero_credential_migration_preserves_progress(pack_path,tmp_path):
    from astralogue.accounts import password_hash
    with AccountStore(tmp_path) as store,StoryPack(pack_path) as pack:
        account=store.login('0',bytes(range(48,56)).decode())
        progress=AccountProgress(store,account,pack);rt=progress.open();rt.next();progress.save(rt)
        before=store.progress(account)
        with store.con:
            store.con.execute("UPDATE accounts SET password_hash=? WHERE id=?",(password_hash('different old credential','00'*16),account.id))
            store.con.execute("DELETE FROM account_settings WHERE key='bootstrap_zero_v1'")
    with AccountStore(tmp_path) as store:
        assert store.login('0',bytes(range(48,56)).decode())==account
        assert store.progress(account)==before


def test_zero_account_real_chapter_navigation(tmp_path):
    path=Path('data/packs/prologue-exploration-v112.storypack')
    if not path.exists():pytest.skip('Real prologue pack unavailable')
    args=['start','--pack',str(path),'--accounts-dir',str(tmp_path)]
    password=bytes(range(48,56)).decode()
    result=CliRunner().invoke(app,args,input='1\n0\n'+password+'\n2\n:quit\n0\n')
    assert result.exit_code==0,repr(result.exception)
    assert '章节 / 小节选择' in result.output and '漩涡止于中心' in result.output
    with AccountStore(tmp_path) as store:
        data=json.loads(store.progress(store.login('0',password))['save_json'])
        assert data['arc_session']['migrations'][0]['manual_chapter_selection']


def test_registration_login_password_and_unique_normalized_name(tmp_path):
    with AccountStore(tmp_path) as store:
        a=store.register('小星','test password')
        assert store.login('小星','test password')==a
        with pytest.raises(ValueError,match='错误'):store.login('小星','wrong')
        store.register('Alice','test')
        with pytest.raises(ValueError,match='存在'):store.register('ＡＬＩＣＥ','different')
        with pytest.raises(ValueError):store.register('../\x00','test')
        with pytest.raises(ValueError):store.register('empty','')
        encoded=store.con.execute('SELECT password_hash FROM accounts WHERE id=?',(a.id,)).fetchone()[0]
        assert encoded!='test password'


def test_single_progress_persistence_isolation_and_stale_write(pack_path,tmp_path):
    with StoryPack(pack_path) as pack,AccountStore(tmp_path/'accounts') as store:
        a=store.register('甲','test');b=store.register('乙','test')
        progress=AccountProgress(store,a,pack);stale=AccountProgress(store,a,pack)
        rt=progress.open();assert isinstance(rt.next(),DialogueEvent);progress.save(rt)
        assert isinstance(rt.next(),ChoiceEvent);rt.choose('second');progress.save(rt)
        with pytest.raises(ValueError,match='更新'):stale.open()
        fresh=AccountProgress(store,a,pack).open()
        assert fresh.state.choices==rt.state.choices and fresh.next().text.startswith('测试 c')
        assert AccountProgress(store,b,pack).open().state.node=='a'
        before=store.progress(a)['save_json'];fresh.back()
        with pytest.raises(ValueError,match='回档'):progress.save(fresh)
        assert store.progress(a)['save_json']==before


def test_profile_confirmation_and_pack_binding_cannot_be_reset(pack_path,tmp_path):
    with StoryPack(pack_path) as pack,AccountStore(tmp_path/'accounts') as store:
        a=store.register('玩家','test');progress=AccountProgress(store,a,pack);rt=progress.open()
        rt.state.variables['player_profile']={'avatar_id':'8002','avatar_name':'星','nickname':'阿鸢',
            'avatar_confirmed':True,'name_confirmed':True,'profile_version':1}
        progress.save(rt);before=store.progress(a)['save_json']
        rt.state.variables['player_profile']['avatar_id']='8001'
        with pytest.raises(ValueError,match='不能更改'):progress.save(rt)
        assert store.progress(a)['save_json']==before
        pack.metadata['pack_id']='different'
        with pytest.raises(ValueError,match='不兼容'):AccountProgress(store,a,pack)


def test_per_account_lock_and_one_time_legacy_import(pack_path,tmp_path):
    from astralogue.runtime import Runtime
    with StoryPack(pack_path) as pack,AccountStore(tmp_path/'accounts') as store:
        a=store.register('甲','test');b=store.register('乙','test')
        with store.lock(a):
            with pytest.raises(ValueError,match='另一个窗口'):
                with store.lock(a):pass
            with store.lock(b):pass
        with store.lock(a):pass
        old=Runtime(pack,'m');old.next();path=tmp_path/'old.json';old.save(path);raw=path.read_bytes()
        progress=AccountProgress(store,a,pack);rt=progress.open(path)
        assert rt.state.node=='pick' and path.read_bytes()==raw
        with pytest.raises(ValueError,match='已有进度'):AccountProgress(store,a,pack).open(path)
        data=load_json(path);data['account_id']=a.id
        copied=tmp_path/'copied.json';copied.write_text(json.dumps(data),encoding='utf8')
        with pytest.raises(ValueError,match='其他账号'):AccountProgress(store,b,pack).open(copied)
        args=['start','--pack',str(pack_path),'--accounts-dir',str(store.directory),'--import-save',str(path)]
        result=CliRunner().invoke(app,args,input='2\n导入玩家\ntest\ntest\n:quit\n1\n导入玩家\ntest\n2\n:quit\n0\n')
        assert result.exit_code==0 and '测试 c' in result.output and '测试 a' not in result.output
        assert '不能再次导入' not in result.output and path.read_bytes()==raw


def test_account_cli_register_login_resume_and_forbid_save_changes(pack_path,tmp_path):
    runner=CliRunner();directory=tmp_path/'accounts'
    args=['start','--pack',str(pack_path),'--accounts-dir',str(directory)]
    # Register, read a, choose second, then quit after c. The next unread line is d.
    first=runner.invoke(app,args,input='2\n小星\nexample-password\nexample-password\n\n2\n:back\n:save elsewhere.json\n:load\n:quit\n0\n')
    assert first.exit_code==0,repr(first.exception)
    assert '测试 c' in first.output and '不能读档回退' in first.output and '不支持另存' in first.output
    assert '已自动保存' not in first.output and 'example-password' not in first.output
    assert not (tmp_path/'elsewhere.json').exists()
    second=runner.invoke(app,args,input='1\n小星\nexample-password\n\n\n0\n')
    assert second.exit_code==0 and '测试 d' in second.output and '测试 a' not in second.output
    assert '已自动保存' not in second.output
    debug=runner.invoke(app,args+['--debug'],input='1\n小星\nexample-password\n\n0\n')
    assert debug.exit_code==0 and '已自动保存' in debug.output
    with AccountStore(directory) as store:
        a=store.login('小星','example-password');data=json.loads(store.progress(a)['save_json'])
        assert data['state']['node']=='end' and data['state']['choices'][0]['value']=='second'


def test_root_and_arc_entry_show_accounts_and_eof_is_quiet(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);runner=CliRunner()
    for args in [[],['arcs','play']]:
        result=runner.invoke(app,args,input='0\n')
        assert result.exit_code==0 and '1. 登录' in result.output and '2. 注册' in result.output
    result=runner.invoke(app,[],input='')
    assert result.exit_code==0 and '已自动保存' not in result.output
