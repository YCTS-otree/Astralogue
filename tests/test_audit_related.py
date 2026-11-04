import json
from astralogue.audit.store import AuditStore
from astralogue.audit.jobs import run
from astralogue.audit.related import related
from astralogue.model import canonical,digest
from test_audit import context,response,FakeProvider


def test_overlap_with_approved_is_reviewed_once_before_application(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        ctx=context();proposal=response()['proposals'][0]
        payload={'context':ctx,'context_hash':digest(ctx),'suggestion':proposal}
        s.db.execute("INSERT INTO proposals(id,payload,status) VALUES(?,?,'approved')",('existing',canonical(payload)));s.db.commit()
        job=s.job(2,'first_task',ctx);s.db.commit();provider=FakeProvider()
        run(s,provider,1)
        assert not s.db.execute('SELECT 1 FROM proposals WHERE job=?',(job,)).fetchone()
        extra=s.db.execute("SELECT * FROM jobs WHERE scope LIKE 'human_feedback:related:%'").fetchone()
        review_context=json.loads(extra['context']);assert review_context['related_review_pass']
        assert review_context['related_applications'][0]['status']=='approved'
        assert review_context['related_applications'][0]['id']=='existing'
        run(s,provider,1,scope=extra['scope'])
        assert provider.calls==2
        assert s.db.execute("SELECT COUNT(*) FROM jobs WHERE scope LIKE 'human_feedback:related:%'").fetchone()[0]==1
        assert s.db.execute('SELECT proposal FROM proposal_links WHERE job=?',(extra['id'],)).fetchone()[0]=='existing'
        assert not s.db.execute('SELECT 1 FROM proposals WHERE job=?',(extra['id'],)).fetchone()
        assert s.db.execute("SELECT status FROM proposals WHERE id='existing'").fetchone()[0]=='approved'


def test_no_overlap_needs_no_extra_round(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        job=s.job(2,'first_task',context());s.db.commit();provider=FakeProvider();run(s,provider,1)
        assert provider.calls==1
        assert s.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1
        assert s.db.execute('SELECT status FROM proposals WHERE job=?',(job,)).fetchone()[0]=='pending'


def test_new_model_notes_must_be_chinese():
    import pytest
    from astralogue.audit.protocol import validate_response
    ctx=context();ctx['require_chinese_notes']=True
    value=response();assert validate_response(value,ctx)
    value['proposals'][0]['explanation']='Move this dialogue to an optional interaction.'
    with pytest.raises(ValueError,match='中文'):validate_response(value,ctx)
