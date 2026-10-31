import os
from pathlib import Path
from collections import Counter
from copy import deepcopy
import pytest
from astralogue.storypack import StoryPack
from astralogue.runtime import DialogueEvent,ChoiceEvent,EndEvent
from astralogue.arcs.session import ArcSession
from astralogue.model import load_json

@pytest.fixture
def arc():
    value=os.environ.get('ASTRALOGUE_ARC_PACK')
    if not value:pytest.skip('Compiled real chapter pack required')
    with StoryPack(Path(value)) as pack:yield pack

def test_real_chapter_boundaries_and_configuration_order(arc):
    meta=next(iter(arc.metadata['story_arcs'].values()));p=meta['plan']
    assert p['entry']['main']=='1000101' and p['entry']['auto']
    assert p['exit']['from']=='1010001' and p['exit']['to']=='1010002'
    assert len(p['tasks'])==7 and len(p['internal_records'])==16
    ids=[x['id'] for x in p['internal_records']]
    assert ids.index('1000303')<ids.index('1000302')
    assert meta['summary']['source_items']==941 and not meta['gaps']

def test_full_real_chapter_and_restore(arc,tmp_path):
    mid=next(iter(arc.metadata['story_arcs']));rt=ArcSession(arc,mid);seen=set();entered=[];exited=[]
    for step in range(2500):
        e=rt.next();n=arc.node(e.node)
        if isinstance(e,EndEvent):break
        assert e.node not in seen;seen.add(e.node)
        if isinstance(e,ChoiceEvent):rt.choose(n.data.get('recorded_value') or ('recorded' if any(o.value=='recorded' for o in e.options) else e.options[0].value))
        else:assert isinstance(e,DialogueEvent)
        if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
        if n.data.get('arc_action')=='task_exit':exited.append(n.data['task'])
        if step==300:rt.save(tmp_path/'mid.json');rt=ArcSession.load(arc,tmp_path/'mid.json')
    else:pytest.fail('chapter did not reach exit')
    assert entered==exited==list(range(7))
    assert len(rt.traversal)>941 and all(r['provenance'] for r in rt.traversal)
    rt.previous();assert isinstance(rt.next(),DialogueEvent)
    rt.save(tmp_path/'end.json');loaded=ArcSession.load(arc,tmp_path/'end.json')
    assert loaded.traversal==rt.traversal

def test_all_projected_native_choices_match_original_paths(arc):
    mid=next(iter(arc.metadata['story_arcs']));meta=arc.metadata['story_arcs'][mid]
    for injection in meta['injections']:
        def visit(rt,trace,depth=0):
            assert depth<100
            n=arc.node(rt.state.node)
            if not n.data.get('native_span'):return [trace]
            e=rt.next()
            if isinstance(e,DialogueEvent):return visit(rt,trace+[n.data['sentence_id']],depth+1)
            assert isinstance(e,ChoiceEvent);out=[]
            for option in e.options:
                child=ArcSession(arc,mid);child.state=deepcopy(rt.state);child.choose(option.value)
                out+=visit(child,trace+[n.data['source_option_ids'][option.value]],depth+1)
            return out
        rt=ArcSession(arc,mid);rt.state.node=injection['compiled_entry']
        assert sorted(visit(rt,[]))==sorted(injection['paths'])

def test_same_target_choice_audits_correct_edge(graph,tmp_path):
    from astralogue.compiler import compile_story
    graph.metadata['narrative']={'relations':{}};graph.metadata['story_arcs']={'m':{}}
    for e in graph.edges:
        if e.source=='pick':e.target='b'
    path=tmp_path/'same.storypack';compile_story(graph,path)
    with StoryPack(path) as pack:
        rt=ArcSession(pack,'m');rt.next();rt.next();rt.choose('second')
        assert rt.traversal[-1]['value']=='second'
        rt.back();assert isinstance(rt.next(),ChoiceEvent)
        rt.choose('first');assert rt.traversal[-1]['value']=='first'
