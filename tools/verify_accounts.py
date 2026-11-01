"""Real prologue through registration, silent checkpoints, login and completion."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

from astralogue.accounts import AccountStore,AccountProgress
from astralogue.arcs.session import ArcSession
from astralogue.player import ProfileEvent
from astralogue.runtime import ChoiceEvent,DialogueEvent,EndEvent
from astralogue.storypack import StoryPack
from astralogue.adapters.hf import write

folder=Path('data/staging/accounts-verification').resolve();folder.mkdir(parents=True,exist_ok=True)
path=Path('data/packs/prologue-player.storypack').resolve()
# Every verification run owns a fresh DB; previous runs and user accounts stay intact.
directory=Path(tempfile.mkdtemp(prefix='run-',dir=folder))
with StoryPack(path) as pack:
    mid=next(iter(pack.metadata['story_arcs']));rt=ArcSession(pack,mid)
    first=['2','verification-A','local-test-only','local-test-only'];second=['1','verification-A','local-test-only']
    commands=first;split=False;entered=[];exited=[]
    for step in range(2500):
        e=rt.next();n=pack.node(e.node)
        if isinstance(e,ProfileEvent):
            value={'avatar':'8001','avatar_confirm':'confirm','name':'账号阿鸢','name_confirm':'confirm'}[e.stage]
            commands.append(str(list(e.avatars).index(value)+1) if e.stage=='avatar' else '1' if e.stage.endswith('confirm') else value)
            rt.identity_input(value);continue
        if isinstance(e,EndEvent):commands.extend(['','0']);break
        assert isinstance(e,(DialogueEvent,ChoiceEvent)),e
        if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
        if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
        if isinstance(e,DialogueEvent):
            if not split and step>390:
                commands.extend([':back',':save other.json',':load',':quit','0'])
                expected_mid=rt.snapshot();split=True;commands=second;continue
            commands.append('')
        else:
            values={o.value for o in e.options};preferred=n.data.get('recorded_value')
            value=preferred if preferred in values else n.data.get('continuation_value') or ('recorded' if 'recorded' in values else e.options[0].value)
            commands.append(str(next(i for i,o in enumerate(e.options,1) if o.value==value)));rt.choose(value)
    else:raise AssertionError('Full chapter did not end')
    assert split and entered==exited==list(range(7))
    env={**os.environ,'PYTHONIOENCODING':'utf-8','HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'}
    denied=[str(Path(p).resolve()) for p in ['data/raw','data/external','data/staging/bwiki','data/staging/animestudio',r'G:\Program Files']]
    guard="""import sys,os,runpy,json
denied=[os.path.normcase(os.path.abspath(p)) for p in json.loads(sys.argv[1])]
def check(event,args):
 if event=='socket.connect':raise AssertionError('Network forbidden')
 if event=='open' and isinstance(args[0],str):
  p=os.path.normcase(os.path.abspath(args[0]))
  if any(p==q or p.startswith(q+os.sep) for q in denied):raise AssertionError('Upstream input forbidden')
sys.addaudithook(check)
sys.argv=['astralogue',*sys.argv[2:]]
runpy.run_module('astralogue',run_name='__main__')
"""
    args=[sys.executable,'-c',guard,json.dumps(denied),'start','--pack',str(path),'--accounts-dir',str(directory)]
    with tempfile.TemporaryDirectory() as cwd:
        for label,inputs in [('register',first),('login',second),('new-account',['2','verification-B','another-local-test','another-local-test',':quit','0']),
                             ('completed-login',['1','verification-A','local-test-only',':back','','0'])]:
            result=subprocess.run(args,input='\n'.join(inputs)+'\n',encoding='utf8',capture_output=True,cwd=cwd,env=env,timeout=300)
            (folder/(label+'.txt')).write_text(result.stdout+result.stderr,encoding='utf8')
            assert result.returncode==0,result.stderr
            assert all(x not in result.stdout for x in ['已自动保存','local-test-only','another-local-test','[Reader]','【社区转录·'])
            if label in {'login','completed-login'}:assert '本章阅读结束' in result.stdout
            if label=='completed-login':assert '【进入任务】' not in result.stdout and '开场动画' not in result.stdout
            with AccountStore(directory) as store:
                a=store.login('verification-A','local-test-only');current=AccountProgress(store,a,pack).open()
                if label=='register':assert current.snapshot()==expected_mid
                elif label in {'login','completed-login'}:
                    assert current.snapshot()==rt.snapshot() and current.traversal==rt.traversal
                if label=='new-account':
                    b=store.login('verification-B','another-local-test');other=AccountProgress(store,b,pack).open()
                    assert other.state.node!=current.state.node and other.profile.nickname is None
        debug=subprocess.run(args+['--debug'],input='1\nverification-A\nlocal-test-only\n\n0\n',encoding='utf8',capture_output=True,cwd=cwd,env=env,timeout=30)
        assert debug.returncode==0 and '已自动保存' in debug.stdout
        (folder/'debug.txt').write_text(debug.stdout+debug.stderr,encoding='utf8')
    write(Path('data/accounts-verification.json'),{'account_database':str(directory/'accounts.sqlite'),'reader_complete':True,
        'entered':entered,'exited':exited,'identity':rt.profile.to_dict(),'separate_account_starts_independently':True,
        'completed_login_does_not_restart':True,'silent_autosave':True,'debug_save_notice':True,
        'save_mutation_commands_rejected':True,'runtime_network_and_upstream_access_forbidden':True,'cli_exit_codes':[0,0,0,0,0]})
print('Account CLI verified: registration, mid-chapter login, full prologue exit, isolated second account, locked completed progress and debug-only save notices.')
