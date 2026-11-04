import json
import pytest
from astralogue.audit.store import AuditStore
from astralogue.audit.undo import undo
from astralogue.audit.review import review
from astralogue.audit.feedback import submit_feedback
from astralogue.audit.pages import detail_page
from astralogue.model import canonical,digest
from test_audit import context,response,FakeProvider


def root(store,pid='root'):
    ctx=context();p=response()['proposals'][0]
    store.db.execute('INSERT INTO proposals(id,payload) VALUES(?,?)',(pid,canonical({'context':ctx,'context_hash':digest(ctx),'suggestion':p,'origin':'test'})));store.db.commit()


def test_undo_reject_restores_pending_without_losing_history(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        root(s);review(s,'root','reject','human')
        assert 'undo_reject' in detail_page(s,'root','token','human')
        undo(s,'root','undo_reject','human')
        assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='pending'
        assert s.db.execute('SELECT COUNT(*) FROM review_log').fetchone()[0]==2
        with pytest.raises(ValueError):undo(s,'root','undo_reject','human')


def test_research_undo_cascades_all_rounds_and_descendants(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        root(s);first=submit_feedback(s,'root','research_approve','human','修改方向')
        ctx=context();ctx['parent_proposal']='root'
        child={'context':ctx,'context_hash':digest(ctx),'suggestion':response()['proposals'][0]}
        s.db.execute('INSERT INTO proposals(id,job,payload) VALUES(?,?,?)',('child',first,canonical(child)));s.db.commit()
        second=submit_feedback(s,'child','request_changes','human','进一步修正')
        ctx2=context();ctx2['parent_proposal']='child';child['context']=ctx2
        s.db.execute("INSERT INTO proposals(id,job,payload,status) VALUES(?,?,?,'approved')",('grandchild',second,canonical(child)));s.db.commit()
        result=undo(s,'root','undo_research','human')
        assert result=={'withdrawn':2,'cancelled_jobs':2}
        assert dict(s.db.execute('SELECT id,status FROM proposals'))=={'root':'pending','child':'withdrawn','grandchild':'withdrawn'}
        assert set(r[0] for r in s.db.execute('SELECT status FROM jobs'))=={'cancelled'}
        with pytest.raises(ValueError):review(s,'child','approve','human')
        with pytest.raises(ValueError):submit_feedback(s,'child','request_changes','human','不能恢复已撤回申请')
        with pytest.raises(ValueError):undo(s,'root','undo_research','human')


def test_running_result_is_discarded_after_undo(tmp_path):
    from astralogue.audit.jobs import run
    path=tmp_path/'a.sqlite'
    with AuditStore(path) as s:
        root(s);job=submit_feedback(s,'root','research_approve','human','修改')
        scope=s.db.execute('SELECT scope FROM jobs WHERE id=?',(job,)).fetchone()[0]
        class CompletingProvider(FakeProvider):
            def run(self,*args):
                with AuditStore(path) as other:undo(other,'root','undo_research','human')
                value=response();value['proposals'][0]['after']['interaction']='新入口'
                return json.dumps(value),{'input_tokens':10,'output_tokens':10,'cost':0,'seconds':.01}
        run(s,CompletingProvider(),1,scope=scope)
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]=='cancelled'
        assert s.db.execute('SELECT COUNT(*) FROM proposals WHERE job=?',(job,)).fetchone()[0]==0
        assert json.loads(s.db.execute('SELECT metadata FROM calls WHERE job=?',(job,)).fetchone()[0])['discarded_after_research_undo']

def test_research_rollback_preserves_unrelated_later_publication(tmp_path):
    from copy import deepcopy
    from test_audit_cleanup import fixture
    from astralogue.compiler import compile_story
    from astralogue.audit.publication import publish,rollback_research
    from astralogue.storypack import StoryPack
    b,patch=fixture();path=tmp_path/'p.storypack';compile_story(b,path)
    publish(path,'research',patch)
    second=deepcopy(patch);second['id']='foreign'
    op=second['operations'][0];op['source']='b';op['nodes']=['b'];op['before_hashes']={'b':digest(next(n for n in b.nodes if n.id=='b').__dict__)};op['suggestion']['operation']='mark_as_required'
    publish(path,'foreign',second)
    with pytest.raises(ValueError,match='其他研究'):rollback_research(path,{'research'})
    with StoryPack(path) as p:assert p.metadata['live_revision']['number']==2
    assert rollback_research(path,{'foreign'})==['foreign']
    assert rollback_research(path,{'research'})==['research']
    with StoryPack(path) as p:assert 'live_revision' not in p.metadata

def test_http_undo_actions_and_research_cascade(tmp_path):
    import threading,urllib.request,urllib.parse
    from astralogue.audit.webui import make_server
    path=tmp_path/'audit.sqlite'
    with AuditStore(path) as s:
        root(s);submit_feedback(s,'root','research_approve','human','修改方向')
        root(s,'rejected');review(s,'rejected','reject','human')
    server=make_server(path,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base='http://127.0.0.1:'+str(server.server_address[1])
        with AuditStore(path) as s:token=s.setting('webui_csrf')
        html=urllib.request.urlopen(base+'/?id=root').read().decode();assert 'undo_research' in html
        for pid,action in [('root','undo_research'),('rejected','undo_reject')]:
            req=urllib.request.Request(base,data=urllib.parse.urlencode({'id':pid,'action':action,'reviewer':'human','csrf':token}).encode(),headers={'Accept':'application/json'})
            result=json.load(urllib.request.urlopen(req));assert '撤销' in result['message']
        with AuditStore(path) as s:assert set(r[0] for r in s.db.execute('SELECT status FROM proposals'))=={'pending'}
    finally:server.shutdown();server.server_close();thread.join()
