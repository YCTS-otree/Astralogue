from pathlib import Path
import pytest
from astralogue.model import Bundle,Node,Edge,Mission,digest
from astralogue.audit.cleanup import compile_cleanup
from astralogue.narrative.patch import validate_patch
from astralogue.compiler import compile_story
from astralogue.storypack import StoryPack
from astralogue.arcs.session import ArcSession
from astralogue.runtime import ChoiceEvent,DialogueEvent,EndEvent


def fixture():
    b=Bundle(metadata={'version':'test','story_arcs':{'reader':{}},'narrative':{'game':'test','game_version':'v','source_hashes':{'x':'hash'},'modes':{'reader':{'mode':'reader'}},'relations':{}}})
    b.text('default-title','test');b.missions=[Mission('reader','default-title','a')]
    for name in ['a','o1','o2','b']:b.nodes.append(Node(name,'reader','dialogue',b.text(name,name),data={'task':0}))
    b.nodes.append(Node('end','reader','end'))
    for i,(a,z) in enumerate(zip(['a','o1','o2','b'],['o1','o2','b','end'])):
        e=Edge(str(i),a,z);b.edges.append(e);b.metadata['narrative']['relations'][e.id]={'verified':False,'evidence':{'class':'WIKI_ALIGNED'}}
    nodes={n.id:n for n in b.nodes}
    patch={'patch_version':1,'id':'test-review','status':'reviewed','game':'test','game_version':'v','source_hashes':{'x':'hash'},
        'evidence':[{'id':'wiki','uri':'test-source'}],'review':{'reviewer':'fixture human','reviewed_at':'2026-11-04','evidence':['wiki']},
        'operations':[{'op':'narrative_audit','source':'o1','nodes':['o1','o2'],'before_hashes':{n:digest(nodes[n].__dict__) for n in ['o1','o2']},
            'reader_only':True,'evidence':['wiki'],'suggestion':{'operation':'move_to_optional_interaction','after':{'candidate_phases':['phase'],'interaction':'额外聊天'}}}]}
    return b,patch


def test_cleanup_main_and_explore_return_save(tmp_path):
    b,patch=fixture();assert validate_patch(b,patch)['valid']
    cleaned=compile_cleanup(b,[patch]);path=tmp_path/'p.storypack';compile_story(cleaned,path)
    assert {n.id:n.text for n in cleaned.nodes if n.id in {'a','o1','o2','b'}}=={n.id:n.text for n in b.nodes if n.kind=='dialogue'}
    with StoryPack(path) as p:
        rt=ArcSession(p,'reader');assert rt.next().text=='a'
        menu=rt.next();assert isinstance(menu,ChoiceEvent)
        rt.choose('main');assert rt.next().text=='b';assert isinstance(rt.next(),EndEvent)
        rt=ArcSession(p,'reader');rt.next();rt.next();rt.choose('test-review');assert rt.next().text=='o1'
        rt.save(tmp_path/'save.json');rt=ArcSession.load(p,tmp_path/'save.json');assert rt.next().text=='o2'
        back=rt.next();assert isinstance(back,ChoiceEvent) and back.node==menu.node
        assert [o.value for o in back.options]==['main'];rt.choose('main');assert rt.next().text=='b'


def test_pending_stale_overlap_and_verified_rejected():
    b,p=fixture();p['status']='pending'
    with pytest.raises(ValueError):compile_cleanup(b,[p])
    b,p=fixture();b.nodes[1].data['changed']=True
    with pytest.raises(ValueError):compile_cleanup(b,[p])
    b,p=fixture();b.metadata['narrative']['relations']['0']['verified']=True
    with pytest.raises(ValueError,match='Verified'):compile_cleanup(b,[p])
    b,p=fixture()
    with pytest.raises(ValueError,match='overlap'):compile_cleanup(b,[p,p])


def test_reuses_existing_phase_without_duplicate_optional_playback(tmp_path):
    b,p=fixture();mid='reader'
    for e in b.edges:
        if e.source=='o2':e.target='menu'
    b.metadata['mission_initial_variables']={mid:{'read-old':False}}
    b.nodes.extend([Node('menu',mid,'choice',data={'reader_action':'free_exploration','scene_id':'phase','source':{'interaction':{'source':{'sha256':'wiki','start':1}}}}),
                    Node('old-copy',mid,'dialogue',b.text('old-copy-text','old copied optional')),
                    Node('read-mark',mid,'set',data={'var':'read-old','value':True})])
    b.edges.extend([Edge('main','menu','b','option',b.text('main','main'),value='main'),
                    Edge('optional','menu','old-copy','option',b.text('optional','optional'),{'eq':[{'var':'read-old'},False]},'optional'),
                    Edge('copy-next','old-copy','read-mark'),Edge('copy-return','read-mark','menu')])
    p['evidence'][0]['record']={'source':{'sha256':'wiki','start':1}}
    cleaned=compile_cleanup(b,[p]);compile_story(cleaned,tmp_path/'p.storypack')
    assert cleaned.metadata['audit_cleanup']['applied'][0]['duplicate_source_branch_replaced']
    with StoryPack(tmp_path/'p.storypack') as pack:
        rt=ArcSession(pack,mid);assert rt.next().text=='a';assert rt.next().node=='menu'
        rt.choose('optional');assert rt.next().text=='o1';assert rt.next().text=='o2'
        assert [o.value for o in rt.next().options]==['main'];rt.choose('main');assert rt.next().text=='b'
