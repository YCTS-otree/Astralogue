"""Two actual CLI tours of first-task scope, with exact event difference evidence."""
from pathlib import Path
import json,os,subprocess,sys,tempfile
from astralogue.accounts import AccountStore,AccountProgress
from astralogue.arcs.session import ArcSession
from astralogue.runtime import DialogueEvent,ChoiceEvent
from astralogue.player import ProfileEvent
from astralogue.storypack import StoryPack
from astralogue.adapters.hf import write


def tour(pack_path,explore,label,folder):
    with StoryPack(pack_path) as p:
        mid=next(iter(p.metadata['story_arcs']));arc=p.metadata['story_arcs'][mid];stop=arc['task_boundaries'][0]['exit']
        rt=ArcSession(p,mid);events=[];visited=set();commands=['2',label,'fixture-pass','fixture-pass']
        for _ in range(2000):
            if rt.state.node==stop:break
            e=rt.next();n=p.node(e.node)
            if isinstance(e,ProfileEvent):
                v={'avatar':next(iter(e.avatars)),'avatar_confirm':'confirm','name':'审计档案','name_confirm':'confirm'}[e.stage]
                commands.append(str(list(e.avatars).index(v)+1) if e.stage=='avatar' else '1' if e.stage.endswith('confirm') else v);rt.identity_input(v)
            elif isinstance(e,DialogueEvent):
                if e.node in visited:raise AssertionError('Unexpected repeated dialogue')
                visited.add(e.node);events.append({'node':e.node,'speaker':e.speaker,'text':e.text,'data':n.data});commands.append('')
            elif isinstance(e,ChoiceEvent):
                values={o.value for o in e.options}
                if n.data.get('reader_action')=='free_exploration':value=next((o.value for o in e.options if o.value!='main'),'main') if explore else 'main'
                else:
                    value=n.data.get('continuation_value')
                    if value not in values:value=n.data.get('recorded_value')
                    if value not in values:value=e.options[0].value
                commands.append(str(next(i for i,o in enumerate(e.options,1) if o.value==value)));rt.choose(value)
            else:raise AssertionError(e)
        else:raise AssertionError('Task boundary not reached')
        commands.append('0')
        with tempfile.TemporaryDirectory(dir=folder) as accounts:
            result=subprocess.run([sys.executable,'-m','astralogue','start','--pack',str(pack_path),'--accounts-dir',accounts],
                input='\n'.join(commands)+'\n',encoding='utf8',capture_output=True,env={**os.environ,'PYTHONIOENCODING':'utf-8'},timeout=120)
            (folder/(label+'.txt')).write_text(result.stdout+result.stderr,encoding='utf8')
            assert result.returncode==0 and '本节阅读结束' in result.stdout,result.stderr
            with AccountStore(Path(accounts)) as store:
                rt_cli=AccountProgress(store,store.login(label,'fixture-pass'),p).open()
                assert rt_cli.snapshot()==rt.snapshot() and rt_cli.traversal==rt.traversal
        write(folder/(label+'.json'),{'pack_id':p.metadata['pack_id'],'events':events,'trace':rt.traversal,'last_node':rt.state.node})
        return events


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--pack',type=Path,default=Path('data/packs/prologue-exploration-v112.storypack'));args=parser.parse_args()
    folder=Path('data/audit/path-verification').resolve();folder.mkdir(parents=True,exist_ok=True)
    a=tour(args.pack.resolve(),False,'path-A',folder);b=tour(args.pack.resolve(),True,'path-B',folder)
    aset={x['node'] for x in a};bset={x['node'] for x in b};extra=[x['node'] for x in b if x['node'] not in aset]
    assert aset<=bset
    write(Path('data/audit/path-comparison.json'),{'path_A_events':len(a),'path_B_events':len(b),'B_only_nodes':extra,'A_missing_in_B':[],
        'cli_validated':True,'snapshot_and_audit_exact':True,'scope':'current published first task; NOT an approved cleanup result'})
    print('First-task A/B CLI tours and event differences verified; no proposals auto-approved.')
