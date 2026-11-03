from pathlib import Path
import os
import pytest
from astralogue.arcs.session import ArcSession
from astralogue.arcs.exploration import compile_exploration
from astralogue.compiler import compile_story
from astralogue.runtime import ChoiceEvent, DialogueEvent
from astralogue.storypack import StoryPack


@pytest.fixture
def exploration(tmp_path):
    source=Path(os.environ.get('ASTRALOGUE_PLAYER_PACK','data/packs/prologue-player.storypack'))
    snapshots=Path('data/staging/bwiki')
    if not source.exists() or not (snapshots/'混乱行至深处.json').exists():pytest.skip('Real prologue/BWIKI cache unavailable')
    with StoryPack(source) as sp:
        before=sp.bundle();b=sp.bundle()
        report=compile_exploration(b,[snapshots/(x+'.json') for x in ['混乱行至深处','漩涡止于中心']])
        strict=set(n.id for n in before.nodes if n.mission!=before.metadata['narrative']['entries']['reader'])
        assert [n for n in b.nodes if n.id in strict]==[n for n in before.nodes if n.id in strict]
        assert [e for e in b.edges if e.source in strict]==[e for e in before.edges if e.source in strict]
    output=tmp_path/'exploration.storypack';compile_story(b,output)
    with StoryPack(output) as p:yield p,report


def test_real_two_scenes_return_once_save_and_rewind(exploration,tmp_path):
    p,r=exploration;mid=next(iter(p.metadata['story_arcs']))
    assert len(r['scenes'])==2 and r['removed_from_default']==1
    for scene in r['scenes']:
        rt=ArcSession(p,mid);rt.state.node=scene['menu']
        assert {o.value for o in rt.next().options}=={'main','explore'}
        mark=rt.checkpoint();rt.choose('explore');e=rt.next();assert isinstance(e,DialogueEvent)
        rt.save(tmp_path/'mid.json');rt=ArcSession.load(p,tmp_path/'mid.json')
        event=rt.next();assert isinstance(event,ChoiceEvent) and event.node==scene['menu']
        assert [o.value for o in event.options]==['main']
        rt.save(tmp_path/'menu.json');rt=ArcSession.load(p,tmp_path/'menu.json')
        assert len(rt.next().options)==1
        rt.restore(mark);assert len(rt.next().options)==2
        rt.choose('main');event=rt.next();assert event.node==scene['main_target']
        assert rt.state.variables['current_exploration_node'] is None
        other=ArcSession(p,mid);other.state.node=scene['menu'];assert len(other.next().options)==2


def test_unproved_interactions_remain_unconnected(exploration):
    p,r=exploration
    assert any(x.get('label')=='调查桌面' for x in r['unconnected'])
    for s in r['scenes']:
        n=p.node(s['menu']);assert n.data['availability'].endswith('game_condition_unknown')
        assert all(p.metadata['narrative']['relations'][e.id]['verified'] is False for e in p.edges(n.id))
