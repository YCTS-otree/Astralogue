import sqlite3
import pytest
from astralogue.compiler import compile_story
from astralogue.storypack import StoryPack
from astralogue.arcs.session import ArcSession
from astralogue.runtime import ChoiceEvent,DialogueEvent
from astralogue.audit.publication import publish,rollback
from test_audit_cleanup import fixture


def test_live_publish_updates_open_reader_and_preserves_saved_identity(tmp_path):
    b,patch=fixture();path=tmp_path/'p.storypack';compile_story(b,path)
    with StoryPack(path) as pack:
        identity=pack.metadata['pack_id'];rt=ArcSession(pack,'reader');save=tmp_path/'save.json';rt.save(save)
        result=publish(path,'proposal',patch)
        assert result['status']=='published' and result['changed_rows']>0
        assert publish(path,'proposal',patch)['status']=='already_published'
        assert rt.next().text=='a'
        event=rt.next();assert isinstance(event,ChoiceEvent)
        rt.choose('main');assert rt.next().text=='b'
        assert pack.metadata['pack_id']==identity
        restored=ArcSession.load(pack,save);assert restored.next().text=='a'
        assert isinstance(restored.next(),ChoiceEvent)
        assert restored.state.variables['_astralogue_live_revision']==1
    with StoryPack(path) as pack:
        rt=ArcSession(pack,'reader');rt.next();rt.next();rt.choose('test-review')
        assert rt.next().text=='o1' and rt.next().text=='o2'
        assert isinstance(rt.next(),ChoiceEvent)
    assert rollback(path)==1
    with StoryPack(path) as pack:
        rt=ArcSession(pack,'reader');assert rt.next().text=='a' and rt.next().text=='o1'
        assert 'live_revision' not in pack.metadata
    assert not list(tmp_path.glob('*.bak')) and len(list(tmp_path.glob('*.storypack')))==1


def test_invalid_publish_has_no_partial_graph_changes(tmp_path):
    b,patch=fixture();path=tmp_path/'p.storypack';compile_story(b,path)
    patch['operations'][0]['before_hashes']['o1']='stale'
    with StoryPack(path) as pack:before=pack.bundle().to_dict()
    with pytest.raises(ValueError):publish(path,'bad',patch)
    with StoryPack(path) as pack:assert pack.bundle().to_dict()==before
    con=sqlite3.connect(path);assert con.execute('SELECT COUNT(*) FROM reader_revisions').fetchone()[0]==0;con.close()


def test_overlap_and_history_integrity_are_guarded(tmp_path):
    b,patch=fixture();path=tmp_path/'p.storypack';compile_story(b,path);publish(path,'one',patch)
    with pytest.raises(ValueError,match='重叠'):publish(path,'two',patch)
    con=sqlite3.connect(path);con.execute("UPDATE reader_revisions SET sha256='broken'");con.commit();con.close()
    with pytest.raises(ValueError,match='校验'):rollback(path)
    with StoryPack(path) as pack:assert pack.metadata['live_revision']['number']==1

def test_approved_audit_publishes_once_and_preserves_base_identity(tmp_path):
    from astralogue.audit.store import AuditStore
    from astralogue.audit.publication import publish_approved
    from astralogue.model import canonical,digest
    b,patch=fixture();path=tmp_path/'p.storypack';compile_story(b,path)
    nodes={n.id:n for n in b.nodes}
    context={'instances':{'a':{'node':'o1'},'b':{'node':'o2'}},'scenes':{'phase':{'id':'phase'}},
             'evidence':{'wiki':{'label':'额外对话'},'graph':{'source_hashes':{'x':'hash'}}}}
    suggestion={'operation':'move_to_optional_interaction','instances':['a','b'],'targets':[],'evidence':['wiki','graph'],
                'before':{},'after':{'candidate_phases':['phase'],'interaction':'额外聊天'},'unknowns':[],'conflicts':[],'rationale':'fixture'}
    payload={'context':context,'context_hash':digest(context),'suggestion':suggestion,'origin':'test'}
    with AuditStore(tmp_path/'audit.sqlite') as s:
        s.setting('publication_pack',str(path))
        s.db.execute("INSERT INTO proposals(id,payload,status,reviewer,reviewed_at) VALUES(?,?,'approved','fixture human',1)",('proposal',canonical(payload)));s.db.commit()
        assert publish_approved(s,['proposal'])[0]['status']=='published'
        assert publish_approved(s,['proposal'])[0]['status']=='already_published'
        assert publish_approved(s,['unapproved'])[0]['status']=='failed'
        con=sqlite3.connect(path);assert con.execute('SELECT COUNT(*) FROM reader_revisions').fetchone()[0]==1;con.close()

def test_repeat_inspection_cannot_publish_as_one_optional_body(tmp_path):
    b,patch=fixture();b.texts['o1']['CHS']='首次调查。\n再次调查：重复访问。'
    path=tmp_path/'p.storypack';compile_story(b,path)
    with pytest.raises(ValueError,match='再次调查'):publish(path,'mixed',patch)
