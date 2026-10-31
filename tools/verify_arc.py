"""Run an entire chapter, not independent snippets; persist an edge-by-edge audit."""
from pathlib import Path
from collections import Counter
import os,subprocess,sys,tempfile
from astralogue.storypack import StoryPack
from astralogue.runtime import DialogueEvent,ChoiceEvent,EndEvent,BlockedEvent
from astralogue.arcs.session import ArcSession
from astralogue.adapters.hf import write

path=Path('data/packs/prologue-arc.storypack');folder=Path('data/staging/m9');folder.mkdir(parents=True,exist_ok=True)
with StoryPack(path) as pack:
    mid=pack.metadata['narrative']['entries']['reader'];meta=pack.metadata['story_arcs'][mid];rt=ArcSession(pack,mid)
    source_rows=set();entered=[];exited=[];inputs=[];events=[];seen=set();kinds=Counter();origins=Counter();native_traces={}
    for step in range(3000):
        e=rt.next();n=pack.node(e.node);inputs.append('')
        if isinstance(e,DialogueEvent):
            events.append({'node':e.node,'speaker':e.speaker,'text':e.text,'data':n.data})
            origins[n.data.get('content_origin','progress')]+=1;kinds[n.data.get('content_kind','dialogue')]+=1
            if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
            if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
        elif isinstance(e,ChoiceEvent):
            value=n.data.get('recorded_value') or ('recorded' if any(o.value=='recorded' for o in e.options) else e.options[0].value)
            events.append({'node':e.node,'choice':value,'data':n.data});rt.choose(value)
            inputs[-1]=str(next(i+1 for i,o in enumerate(e.options) if o.value==value))
        elif isinstance(e,EndEvent):break
        else:raise AssertionError(e)
        assert e.node not in seen,'duplicate reading node';seen.add(e.node)
        if n.data.get('hf_index') is not None:source_rows.add((n.data['task'],n.data['hf_index']))
        if n.data.get('native_span'):
            span=tuple(n.data['native_span']);key=(n.data['task'],span)
            if n.kind=='dialogue':native_traces.setdefault(key,[]).append(n.data['sentence_id'])
            elif n.kind=='choice':native_traces.setdefault(key,[]).append(n.data['source_option_ids'][value])
            for i in range(span[0],span[1]+1):source_rows.add((n.data['task'],i))
        if step==400:
            rt.save(folder/'mid.save.json');rt=ArcSession.load(pack,folder/'mid.save.json')
    else:raise AssertionError('whole chapter exceeded bound')
    for injection in meta['injections']:
        task=next(i for i,t in enumerate(meta['plan']['tasks']) if t['hf']==injection['file'])
        assert native_traces[(task,(injection['start'],injection['end']))]==injection['recorded']
    expected={(t['task'],i) for t in meta['task_boundaries'] for i in range(t['entries'])}
    assert source_rows==expected,(len(source_rows),len(expected),expected-source_rows)
    assert entered==list(range(7)) and exited==list(range(7))
    assert len(meta['rows'])==941 and len(source_rows)==941
    from itertools import product
    combinations=[]
    for values in product(['1','2','3'],['1','2'],['1','2','3']):
        branch=ArcSession(pack,mid);selections=iter(values);finished=[]
        for _ in range(2000):
            event=branch.next();node=pack.node(event.node)
            if isinstance(event,ChoiceEvent):
                branch.choose(next(selections) if node.data.get('reader_action')=='native_choice' else ('recorded' if any(o.value=='recorded' for o in event.options) else event.options[0].value))
            elif isinstance(event,EndEvent):break
            else:assert isinstance(event,DialogueEvent)
            if node.data.get('arc_action')=='task_exit':finished.append(node.data['task'])
        else:raise AssertionError('Alternative native branch did not finish chapter')
        assert finished==list(range(7));combinations.append(values)
    rt.save(folder/'complete.save.json')
    write(folder/'events.json',events);write(folder/'edge-audit.json',rt.traversal)
    from collections import deque
    reachable=set();queue=deque([pack.mission(mid)['entry']])
    while queue:
        node=queue.popleft()
        if node in reachable:continue
        reachable.add(node);queue.extend(edge.target for edge in pack.edges(node))
    chapter_nodes={n.id for n in pack.bundle().nodes if n.mission==mid}
    assert reachable==chapter_nodes
    source_kinds=Counter();source_dialogue_origins=Counter();game_ids={r['id'] for r in meta['rows'] if r['source']=='GAME'}
    for task in meta['plan']['tasks']:
        raw=pack.metadata['story_arcs'][mid]['hf']['files'][task['hf']]
    # Embedded rows classify original-source dialogue separately from stage directions.
    for row in meta['rows']:
        kind=row.get('kind','對話');source_kinds[kind]+=1
        if kind in {'對話','对话'}:source_dialogue_origins[row['source']]+=1
    write(Path('data/m9-runtime-verification.json'),{'arc':mid,'reader_complete':True,'native_strict_complete':False,'entered':entered,'exited':exited,'source_rows_covered':len(source_rows),'source_rows_total':len(expected),'reachable_arc_nodes':len(reachable),'all_arc_nodes':len(chapter_nodes),'source_kinds':dict(source_kinds),'source_dialogue_origins':dict(source_dialogue_origins),'source_game_distinct_ids':len(game_ids),'source_text_coverage':1.0,'event_count':len(events),'edge_count':len(rt.traversal),'origins':dict(origins),'kinds':dict(kinds),'native_injections':meta['injections'],'known_native_combinations_completed':len(combinations),'manual_task_jumps':0,'blocking_gaps':meta['gaps'],'original_game_all_text_coverage':'unknown; external path only'})
    payload='\n'.join(inputs+[''])
    with tempfile.TemporaryDirectory() as cwd:
        result=subprocess.run([sys.executable,'-m','astralogue','arcs','play','--pack',str(path.resolve())],input=payload,text=True,encoding='utf8',capture_output=True,cwd=cwd,env={**os.environ,'PYTHONIOENCODING':'utf8','HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'},timeout=90)
    (folder/'full-cli.txt').write_text(result.stdout+result.stderr,encoding='utf8')
    assert result.returncode==0 and 'Reader 所选文字阅读段结束' in result.stdout,result.stderr
    print('Whole chapter verified: 7 tasks, 941/941 source rows, no manual task jumps; CLI exit 0')
