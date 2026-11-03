"""Real CLI save/quit/resume, two identities and bounded branch coverage.

Only reads a completed StoryPack. All original-text logs remain under data/.
"""
from copy import deepcopy
from pathlib import Path
from collections import Counter
import os
import json
import subprocess
import sys
import tempfile

from astralogue.adapters.hf import write
from astralogue.arcs.session import ArcSession
from astralogue.model import load_json
from astralogue.player import ProfileEvent
from astralogue.runtime import DialogueEvent, ChoiceEvent, EndEvent
from astralogue.storypack import StoryPack

PACK=Path('data/packs/prologue-player.storypack').resolve()
FOLDER=Path('data/staging/player-verification').resolve();FOLDER.mkdir(parents=True,exist_ok=True)


def advance(rt, assignments=None):
    entered=[];exited=[];seen=set();events=[];steps=0;covered=set()
    source=rt.pack.metadata['story_arcs'][rt.state.mission]['rows']
    direct={r['node']:(r['file'],r['index']) for r in source if r.get('node')}
    while steps<2500:
        steps+=1;e=rt.next();n=rt.pack.node(e.node)
        if isinstance(e,ProfileEvent):
            rt.identity_input({'avatar':'8002','avatar_confirm':'confirm','name':'分支验证','name_confirm':'confirm'}[e.stage]);continue
        if isinstance(e,EndEvent):return {'entered':entered,'exited':exited,'events':events,'steps':steps,'covered':covered}
        assert isinstance(e,(DialogueEvent,ChoiceEvent)),e
        assert e.node not in seen or n.data.get('reader_action')=='optional_inquiry','Unexpected repeated narrative node';seen.add(e.node)
        if e.node in direct:covered.add(direct[e.node])
        if n.data.get('native_span'):
            start,end=n.data['native_span'];file=rt.pack.metadata['story_arcs'][rt.state.mission]['plan']['tasks'][n.data['task']]['hf']
            covered.update((file,i) for i in range(start,end+1))
        if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
        if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
        if isinstance(e,DialogueEvent):events.append({'node':e.node,'text':e.text,'data':n.data})
        else:
            available={o.value for o in e.options}
            preferred=(assignments or {}).get(e.node) or n.data.get('recorded_value')
            value=preferred if preferred in available else n.data.get('continuation_value') or ('recorded' if 'recorded' in available else e.options[0].value)
            rt.choose(value)
    raise AssertionError('Chapter step bound exceeded')


def cli_identity(pack,mid,label,avatar,nickname,branch_values,reselect):
    rt=ArcSession(pack,mid);before=[];after=[];commands=before;split=False;trace=[];input_name=False
    mid_save=FOLDER/(label+'-mid.save.json');auto=FOLDER/(label+'-auto.save.json')
    entered=[];exited=[]
    for step in range(2500):
        e=rt.next();n=pack.node(e.node)
        if isinstance(e,ProfileEvent):
            if e.stage=='avatar':
                if reselect:
                    first='8002';commands.append(str(list(e.avatars).index(first)+1));rt.identity_input(first)
                    commands.append('2');rt.identity_input('back')
                commands.append(str(list(e.avatars).index(avatar)+1));rt.identity_input(avatar)
            elif e.stage=='avatar_confirm':commands.append('1');rt.identity_input('confirm')
            elif e.stage=='name':
                if not input_name:
                    commands.append('');input_name=True  # rejected blank must not mutate identity
                commands.append(nickname);rt.identity_input(nickname)
            else:commands.append('1');rt.identity_input('confirm')
            continue
        if isinstance(e,EndEvent):commands.append('');break
        assert isinstance(e,(DialogueEvent,ChoiceEvent)),e
        if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
        if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
        if isinstance(e,DialogueEvent):
            trace.append({'node':e.node,'speaker':e.speaker,'text':e.text,'data':n.data})
            if not split and step>390:
                commands.extend([':profile',f':save {mid_save}',':quit']);rt.save(mid_save)
                rt=ArcSession.load(pack,mid_save);split=True;commands=after;continue
            commands.append('')
        else:
            available={o.value for o in e.options};preferred=branch_values.get(e.node) or n.data.get('recorded_value')
            value=preferred if preferred in available else n.data.get('continuation_value') or ('recorded' if 'recorded' in available else e.options[0].value)
            index=next(i for i,o in enumerate(e.options,1) if o.value==value)
            commands.append(str(index));rt.choose(value)
    else:raise AssertionError('CLI simulation did not reach chapter exit')
    assert split and entered==exited==list(range(7))
    env={**os.environ,'PYTHONIOENCODING':'utf-8','HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'}
    denied=[str(Path(x).resolve()) for x in ['data/raw/hsr-mainline','data/external/hf-trailblaze','data/staging/bwiki','data/staging/animestudio',r'G:\Program Files']]
    guard="""import sys,os,runpy,json
denied=[os.path.normcase(os.path.abspath(p)) for p in json.loads(sys.argv[1])]
def check(event,args):
 if event=='socket.connect':raise AssertionError('Playback network access forbidden')
 if event=='open' and isinstance(args[0],str):
  path=os.path.normcase(os.path.abspath(args[0]))
  if any(path==p or path.startswith(p+os.sep) for p in denied):raise AssertionError('Playback upstream input access forbidden')
sys.addaudithook(check)
sys.argv=['astralogue',*sys.argv[2:]]
runpy.run_module('astralogue',run_name='__main__')
"""
    with tempfile.TemporaryDirectory() as cwd:
        prefix=[sys.executable,'-c',guard,json.dumps(denied)]
        commands1=prefix+['play',mid,'--pack',str(PACK),'--autosave',str(auto)]
        commands2=prefix+['resume','--pack',str(PACK),'--save-file',str(mid_save),'--autosave',str(auto)]
        for part,args,inputs in [('start',commands1,before),('resume',commands2,after)]:
            result=subprocess.run(args,input='\n'.join(inputs)+'\n',encoding='utf8',capture_output=True,cwd=cwd,env=env,timeout=120)
            (FOLDER/(label+'-'+part+'.txt')).write_text(result.stdout+result.stderr,encoding='utf8')
            assert result.returncode==0,result.stderr
            if part=='resume':assert '本章阅读结束' in result.stdout
            assert '【社区转录·' not in result.stdout and '[Reader]' not in result.stdout and 'COMMUNITY_TRANSCRIPT' not in result.stdout
    cli=ArcSession.load(pack,auto)
    assert cli.profile.to_dict()==rt.profile.to_dict() and cli.state.node==rt.state.node
    assert cli.state.choices==rt.state.choices and cli.traversal==rt.traversal
    assert any(nickname in x['text'] and x['data'].get('task')==1 for x in trace)
    assert {x['data'].get('task') for x in trace if nickname in x['text']}==set(range(1,7))
    assert not any('{NICKNAME}' in x['text'] for x in trace)
    write(FOLDER/(label+'-events.json'),trace);write(FOLDER/(label+'-edges.json'),cli.traversal)
    return {'profile':cli.profile.to_dict(),'entered':entered,'exited':exited,'cli_exit_codes':[0,0],
            'nickname_dialogues':sum(nickname in x['text'] for x in trace),'manual_task_jumps':0,'reading_end':True}


if __name__=='__main__':
    with StoryPack(PACK) as p:
        mid=next(iter(p.metadata['story_arcs']));report=p.metadata['player_reader']['report']
        kafka=[b for b in report['branches'] if b['page']=='混乱行至深处']
        profiles=[]
        for name,avatar,nickname,values,reselect in [
            ('caelus','8001','阿鸢',[3,2,3],True),('stelle','8002','小星',[1,3,2],False)]:
            selections={b['node']:str(value) for b,value in zip(kafka,values)}
            profiles.append(cli_identity(p,mid,name,avatar,nickname,selections,reselect))
        # Cover every new branch through the COMPLETE chapter, one changed choice
        # at a time. This bounded set is not all possible combined game branches.
        paths=[]
        for branch in report['branches']:
            for e in p.edges(branch['node']):
                result=advance(ArcSession(p,mid),{branch['node']:e.value})
                assert result['entered']==result['exited']==list(range(7))
                paths.append({'node':branch['node'],'value':e.value,'chapter_exit':True})
        # Preserve all 18 combinations of the two already verified native spans.
        combinations=[{}]
        for injection in p.metadata['story_arcs'][mid]['injections']:
            pending=[(ArcSession(p,mid),{})];local=[];pending[0][0].state.node=injection['compiled_entry']
            while pending:
                rt,choices=pending.pop()
                for _ in range(100):
                    n=p.node(rt.state.node)
                    if not n.data.get('native_span'):local.append(choices);break
                    e=rt.next()
                    if isinstance(e,ChoiceEvent):
                        for o in e.options:
                            child=ArcSession(p,mid);child.state=deepcopy(rt.state);child.choose(o.value)
                            pending.append((child,{**choices,e.node:o.value}))
                        break
            combinations=[{**a,**b} for a in combinations for b in local]
        for selection in combinations:
            result=advance(ArcSession(p,mid),selection)
            assert result['entered']==result['exited']==list(range(7))
        # Ordinary reading skips the explicitly archived carrier waiting thresholds.
        idle=p.metadata['player_reader']['report']['optional_idle']['source_span']
        default=advance(ArcSession(p,mid));assert len(default['covered'])==941-(idle[1]-idle[0]+1)
        original=Counter()
        b=p.bundle()
        for n in b.nodes:
            if n.mission!=mid:continue
            if n.text:original['dialogue_placeholders']+=b.texts[n.text]['CHS'].count('{NICKNAME}')
            for e in p.edges(n.id):
                if e.text:original['option_placeholders']+=b.texts[e.text]['CHS'].count('{NICKNAME}')
        # Strict graph exactly preserved from the input control pack.
        with StoryPack(Path('data/packs/hsr-mainline-m59.storypack')) as strict:
            base=strict.bundle();nmap={n.id:n for n in b.nodes};emap={e.id:e for e in b.edges}
            assert all(nmap[n.id]==n for n in base.nodes)
            assert all(emap[e.id]==e for e in base.edges)
            assert all(b.texts[k]==v for k,v in base.texts.items())
        result={'profiles':profiles,'new_branch_paths':paths,'native_combinations_completed':len(combinations),
            'strict_graph_unchanged':True,'reader_complete':True,'native_strict_complete':False,
            'original_nickname_placeholders':dict(original),'community_annotations':report['annotations'],
            'bwiki_report':report,'source_items':941,'all_default_source_rows_retained':True,
            'branch_coverage':'all six newly projected menus and 18 prior native combinations; remaining game branches unknown'}
        write(Path('data/player-verification.json'),result)
        print(f'Whole prologue: two real CLI identities, save/quit/resume; {len(paths)} BWIKI branch paths; {len(combinations)} native combinations; Strict unchanged.')
