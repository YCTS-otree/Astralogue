import json
import pytest
from astralogue.audit.store import AuditStore
from astralogue.audit.feedback import submit_feedback
from astralogue.audit.pages import detail_page,ordered
from astralogue.audit.review import review
from test_audit_webui import seed


def test_comment_is_required_and_preserved_as_direction_not_approval(tmp_path):
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        with pytest.raises(ValueError):submit_feedback(s,'research','research_approve','human','  ')
        assert s.db.execute('SELECT COUNT(*) FROM review_comments').fetchone()[0]==0
        job=submit_feedback(s,'research','research_approve','human','请定位到原有调查节点，不要直接串播。')
        row=s.db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        ctx=json.loads(row['context'])
        assert ctx['evidence']['human_direction']['kind']=='human_reader_direction_not_game_fact'
        assert s.db.execute("SELECT status FROM proposals WHERE id='research'").fetchone()[0]=='awaiting_revision'
        body=detail_page(s,'research','token','human')
        assert '等待修改' in body and '请定位到原有调查节点' in body and '排队中' in body
        assert 'disabled>等待修改' in body
        assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==0


def test_approved_rejected_buttons_and_expanded_context(tmp_path):
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        review(s,'earlier','approve','human')
        assert 'disabled>已批准' in detail_page(s,'earlier','token','human',8)
        review(s,'later','reject','human')
        html=detail_page(s,'later','token','human',8)
        assert 'disabled>已驳回' in html and 'context=13' in html
        assert 'position:sticky' in html


def test_feedback_result_still_requires_new_human_review(tmp_path):
    from astralogue.audit.jobs import run
    from test_audit import FakeProvider,context
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        p=json.loads(s.db.execute("SELECT payload FROM proposals WHERE id='earlier'").fetchone()[0])
        p['context']=context()
        s.db.execute("UPDATE proposals SET payload=? WHERE id='earlier'",(json.dumps(p),));s.db.commit()
        job=submit_feedback(s,'earlier','request_changes','human','只修改真实节点，不新增文字。')
        scope=s.db.execute('SELECT scope FROM jobs WHERE id=?',(job,)).fetchone()[0]
        run(s,FakeProvider(),1,scope=scope)
        next_job=s.db.execute("SELECT id,scope FROM jobs WHERE scope LIKE 'human_feedback:related:%'").fetchone()
        assert next_job and not s.db.execute('SELECT 1 FROM proposals WHERE job=?',(job,)).fetchone()
        run(s,FakeProvider(),1,scope=next_job['scope'])
        child=s.db.execute('SELECT status,payload FROM proposals WHERE job=?',(next_job['id'],)).fetchone()
        assert child['status']=='pending' and json.loads(child['payload'])['context']['parent_proposal']=='earlier'
        assert s.db.execute("SELECT status FROM proposals WHERE id='earlier'").fetchone()[0]=='revision_submitted'

def test_provider_selection_is_bound_to_feedback_job(tmp_path):
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        job=submit_feedback(s,'research','research_approve','human','请核实原有场景。','deepseek')
        ctx=json.loads(s.db.execute('SELECT context FROM jobs WHERE id=?',(job,)).fetchone()[0])
        assert ctx['feedback_provider']=='deepseek'
        with pytest.raises(ValueError):submit_feedback(s,'research','research_approve','human','内容','unknown')


def test_http_comment_workflow_keeps_research_out_of_approved(tmp_path):
    import threading,urllib.request,urllib.parse,urllib.error
    from astralogue.audit.webui import make_server
    path=tmp_path/'a.sqlite';seed(path);server=make_server(path,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with AuditStore(path) as s:token=s.setting('webui_csrf')
        base='http://127.0.0.1:'+str(server.server_address[1])
        values={'id':'research','csrf':token,'action':'research_approve','reviewer':'human','provider':'local','comment':'定位到具体小节并给出原文依据。'}
        req=urllib.request.Request(base,data=urllib.parse.urlencode(values).encode(),headers={'Accept':'application/json'})
        with urllib.request.urlopen(req) as response:assert '等待模型' in json.load(response)['message']
        with AuditStore(path) as s:
            assert s.db.execute('SELECT COUNT(*) FROM review_comments').fetchone()[0]==1
            assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==0
        html=urllib.request.urlopen(base+'/?id=research&context=8').read().decode()
        assert 'disabled>等待修改' in html and '定位到具体小节' in html
    finally:server.shutdown();server.server_close();thread.join()

def test_feedback_must_resubmit_nonempty_and_changed_proposal():
    from astralogue.audit.protocol import validate_response
    from test_audit import context,response
    ctx=context();ctx['parent_proposal']='parent';value=response()
    ctx['parent_suggestion']=json.loads(json.dumps(value['proposals'][0]))
    assert validate_response(value,ctx)
    from astralogue.audit.references import no_change
    assert no_change(ctx,value)
    ctx['review_intent']='promote_research'
    assert not no_change(ctx,value)
    value['proposals']=[]
    with pytest.raises(ValueError,match='重新|新的待审'):validate_response(value,ctx)

def test_feedback_worker_recovers_interrupted_running_job(tmp_path,monkeypatch):
    from astralogue.audit.feedback import worker
    from test_audit import context,FakeProvider
    import astralogue.audit.providers as providers
    path=tmp_path/'a.sqlite'
    with AuditStore(path) as s:
        jid=s.job(2,'human_feedback:test-recovery',context())
        s.db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,));s.db.commit()
    monkeypatch.setattr(providers,'Provider',lambda *a,**k:FakeProvider())
    class Stop:
        calls=0
        def wait(self,*a):self.calls+=1;return self.calls>1
    worker(path,Stop())
    with AuditStore(path) as s:
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='done'
        assert s.db.execute('SELECT status FROM proposals WHERE job=?',(jid,)).fetchone()[0]=='pending'

def test_feedback_proposal_count_accepts_three_rejects_four():
    from astralogue.audit.protocol import validate_response,constrained_schema
    from test_audit import response,context
    ctx=context();ctx['parent_proposal']='parent';value=response()
    item=value['proposals'][0]
    value['proposals']=[json.loads(json.dumps(item)) for _ in range(3)]
    assert len(validate_response(value,ctx)['proposals'])==3
    assert constrained_schema(ctx)['properties']['proposals']['maxItems']==3
    value['proposals'].append(item)
    with pytest.raises(ValueError,match='最多'):validate_response(value,ctx)

def test_object_partition_keeps_shared_replies_together():
    from astralogue.audit.protocol import validate_response
    from test_audit import context,response
    ctx=context();ctx['parent_proposal']='parent';ctx['reference_instances']={'b':{'node':'stairs-node'}}
    ctx['requested_partitions']=[{'label':'screen','required_aliases':['a']},{'label':'stairs','required_aliases':['b']}]
    value=response();value['proposals'][0]['after']['interaction']='screen'
    second=json.loads(json.dumps(value['proposals'][0]));second['instances']=['b'];second['after']['interaction']='stairs'
    value['proposals'].append(second);assert validate_response(value,ctx)
    value['proposals'][1]['instances']=['a']
    assert validate_response(value,ctx)['review_warnings']

def test_source_bound_additions_and_application_explanation():
    from astralogue.audit.protocol import validate_response
    from test_audit import response,context
    ctx=context();ctx['evidence']['source']['raw']='来源中的准确句子。'
    value=response();p=value['proposals'][0];p['explanation']='补齐有来源的遗漏，说明不是台词。'
    p['additions']=[{'speaker':'旁白','text':'来源中的准确句子。','evidence':['source']}]
    assert validate_response(value,ctx)
    p['additions'][0]['text']='模型编造的句子。'
    with pytest.raises(ValueError,match='原文'):validate_response(value,ctx)
    p['additions'][0].update(text='来源中的准确句子。',evidence=['human_direction'])
    ctx['evidence']['human_direction']={'raw':'来源中的准确句子。'}
    with pytest.raises(ValueError,match='评论'):validate_response(value,ctx)
