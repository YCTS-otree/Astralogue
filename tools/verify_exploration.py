"""Offline real-pack CLI walkthrough, save/resume in an optional interaction."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from astralogue.arcs.session import ArcSession
from astralogue.player import ProfileEvent
from astralogue.runtime import ChoiceEvent, DialogueEvent, EndEvent
from astralogue.storypack import StoryPack
from astralogue.adapters.hf import write

pack_path=Path('data/packs/prologue-exploration-v112.storypack').resolve()
folder=Path('data/staging/exploration-verification').resolve();folder.mkdir(parents=True,exist_ok=True)


def verify(explore):
    label='explore' if explore else 'main'
    saved=folder/(label+'-mid.json');autosave=folder/(label+'-auto.json')
    with StoryPack(pack_path) as pack:
        mid=next(iter(pack.metadata['story_arcs']));rt=ArcSession(pack,mid)
        commands=[[]];visits=[];entered=[];exited=[];menus=set();split=False
        for _ in range(3000):
            e=rt.next();n=pack.node(e.node)
            if isinstance(e,ProfileEvent):
                v={'avatar':'8002','avatar_confirm':'confirm','name':'探索者','name_confirm':'confirm'}[e.stage]
                commands[-1].append(str(list(e.avatars).index(v)+1) if e.stage=='avatar' else '1' if e.stage.endswith('confirm') else v)
                rt.identity_input(v);continue
            if isinstance(e,EndEvent):commands[-1].append('');break
            assert isinstance(e,(ChoiceEvent,DialogueEvent)),e
            if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
            if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
            if isinstance(e,DialogueEvent):
                visits.append(e.node)
                if not split and n.data.get('exploration_interaction'):
                    commands[-1].extend([':save '+str(saved),':quit']);rt.save(saved)
                    rt=ArcSession.load(pack,saved);commands.append([]);split=True;continue
                commands[-1].append('')
            else:
                values={o.value for o in e.options}
                if n.data.get('reader_action')=='free_exploration':
                    menus.add(e.node);value='explore' if explore and 'explore' in values else 'main'
                else:
                    preferred=n.data.get('recorded_value');value=preferred if preferred in values else n.data.get('continuation_value') or ('recorded' if 'recorded' in values else e.options[0].value)
                commands[-1].append(str(next(i for i,o in enumerate(e.options,1) if o.value==value)));rt.choose(value)
        else:raise AssertionError('Chapter failed to finish')
        assert entered==exited==list(range(7)) and len(menus)>=2
        assert len(visits)==len(set(visits)), 'Repeated dialogue'
        expected=rt.snapshot();audit=rt.traversal
        guard="""import sys,runpy,os
def check(event,args):
 if event=='socket.connect':raise AssertionError('Playback must be offline')
 if event=='open' and isinstance(args[0],str):
  p=os.path.normcase(os.path.abspath(args[0]))
  if any(x in p for x in ['data\\\\raw','data\\\\external','staging\\\\bwiki','animestudio']):raise AssertionError('Upstream access')
sys.addaudithook(check)
sys.argv=['astralogue',*sys.argv[1:]]
runpy.run_module('astralogue',run_name='__main__')
"""
        prefix=[sys.executable,'-c',guard]
        with tempfile.TemporaryDirectory() as cwd:
            for i,inputs in enumerate(commands):
                args=(['play',mid] if i==0 else ['resume','--save-file',str(saved)])+['--pack',str(pack_path),'--autosave',str(autosave)]
                p=subprocess.run(prefix+args,input='\n'.join(inputs)+'\n',capture_output=True,encoding='utf8',cwd=cwd,env={**os.environ,'PYTHONIOENCODING':'utf-8'},timeout=180)
                (folder/(label+'-'+str(i)+'.txt')).write_text(p.stdout+p.stderr,encoding='utf8')
                assert p.returncode==0,p.stderr
                if i==len(commands)-1:assert '本章阅读结束' in p.stdout
        actual=ArcSession.load(pack,autosave)
        assert actual.snapshot()==expected and actual.traversal==audit
        return {'entered':entered,'exited':exited,'menus':len(menus),'optional_read':sum(bool(pack.node(n).data.get('exploration_interaction')) for n in visits),
                'save_resume_mid_optional':split,'dialogues':len(visits),'cli_processes':len(commands),'offline':True,'manual_task_jumps':0}


if __name__=='__main__':
    write(Path('data/exploration-verification.json'),{'explore':verify(True),'main':verify(False)})
    print('Full prologue CLI verified: explore/return and main-only, offline save/resume.')
