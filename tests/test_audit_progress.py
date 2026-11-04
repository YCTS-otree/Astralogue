from astralogue.audit.store import AuditStore
from astralogue.audit.feedback import submit_feedback
from astralogue.audit.progress import refresh
from astralogue.audit.review import review
from astralogue.audit.pages import detail_page
from test_audit_undo import root


def test_parent_tracks_queue_failure_and_returned_application(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        root(s);job=submit_feedback(s,'root','research_approve','human','修改方向')
        refresh(s);assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='awaiting_revision'
        s.db.execute("UPDATE jobs SET status='failed',error='模型未落实修改' WHERE id=?",(job,));s.db.commit();refresh(s)
        assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='revision_failed'
        assert '修改失败' in detail_page(s,'root','token','human')
        s.db.execute("UPDATE jobs SET status='done' WHERE id=?",(job,));s.db.commit();refresh(s)
        assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='revision_failed'
        payload=s.db.execute("SELECT payload FROM proposals WHERE id='root'").fetchone()[0]
        s.db.execute('INSERT INTO proposals(id,job,payload) VALUES(?,?,?)',('child',job,payload));s.db.commit();refresh(s)
        assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='revision_submitted'
        assert '已提交返修申请' in detail_page(s,'root','token','human')
        review(s,'root','reject','human');refresh(s)
        assert s.db.execute("SELECT status FROM proposals WHERE id='root'").fetchone()[0]=='rejected'
