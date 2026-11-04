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
        child=s.db.execute('SELECT status,payload FROM proposals WHERE job=?',(job,)).fetchone()
        assert child['status']=='pending' and json.loads(child['payload'])['context']['parent_proposal']=='earlier'
        assert s.db.execute("SELECT status FROM proposals WHERE id='earlier'").fetchone()[0]=='awaiting_revision'

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
