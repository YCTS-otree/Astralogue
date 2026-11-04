import json
from pathlib import Path
from astralogue.audit.store import AuditStore
from astralogue.audit import navigation,rerun
from astralogue.audit.dedup import existing
from astralogue.audit.feedback import submit_feedback
from astralogue.model import canonical
from astralogue.compiler import compile_story
from test_audit_navigation import units
from test_audit_webui import seed
from test_audit_cleanup import fixture
from test_audit import context,response


def test_restart_retains_passed_and_pack_and_has_one_case_per_source(tmp_path,monkeypatch):
    b,_=fixture();path=tmp_path/'p.storypack';compile_story(b,path);before=path.read_bytes()
    monkeypatch.setattr(navigation,'catalog',lambda:units()+units());monkeypatch.setattr(rerun,'catalog',lambda:units()+units())
    db=tmp_path/'a.sqlite';seed(db)
    with AuditStore(db) as s:
        s.setting('publication_pack',str(path))
        s.db.execute("UPDATE proposals SET status='approved' WHERE id='earlier'");old=s.job(2,'unassigned',context());s.db.commit()
        result=rerun.restart(s)
        assert result['approved_kept']==1 and len(result['cases'])==1
        assert s.db.execute("SELECT status,deleted_at FROM proposals WHERE id='earlier'").fetchone()[:]==('approved',None)
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(old,)).fetchone()[0]=='cancelled'
        assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE deleted_at IS NULL AND status!='approved'").fetchone()[0]==1
        assert path.read_bytes()==before


def test_exact_proposal_reuses_existing_but_not_archived(tmp_path):
    ctx=context();proposal=response()['proposals'][0]
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.db.execute('INSERT INTO proposals(id,payload) VALUES(?,?)',('existing',canonical({'context':ctx,'suggestion':proposal})));s.db.commit()
        assert existing(s,ctx,proposal)=='existing'
        changed=json.loads(json.dumps(proposal));changed['rationale']='不同说明但相同修改'
        assert existing(s,ctx,changed)=='existing'
        s.db.execute("UPDATE proposals SET deleted_at=1 WHERE id='existing'");s.db.commit()
        assert existing(s,ctx,proposal) is None


def test_new_comment_cancels_old_unfinished_round(tmp_path):
    from test_audit_undo import root
    with AuditStore(tmp_path/'a.sqlite') as s:
        root(s);a=submit_feedback(s,'root','research_approve','human','第一轮')
        b=submit_feedback(s,'root','request_changes','human','新的更正方向')
        assert a!=b
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(a,)).fetchone()[0]=='cancelled'
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(b,)).fetchone()[0]=='pending'
