import json
from pathlib import Path
import pytest
from astralogue.audit.store import AuditStore
from astralogue.audit.protocol import validate_response
from astralogue.audit.jobs import run
from astralogue.audit.review import review
from astralogue.audit.providers import Provider


def context():
    return {'instances':{'a':{'node':'real-node'}},'evidence':{'source':{'sha256':'bound'}},'scenes':{'phase':{'id':'real-phase'}}}


def response():
    return {'classifications':[{'instance':'a','category':'OPTIONAL_NPC','evidence':['source'],'condition':'UNKNOWN','scenes':['phase'],'uncertainty':'timing unknown','counterevidence':[]}],
            'proposals':[{'operation':'move_to_optional_interaction','instances':['a'],'targets':[],'evidence':['source'],
                          'before':{'node':'real-node'},'after':{'phase':'real-phase'},'conflicts':[],'unknowns':['trigger'],'rationale':'Explicit optional source label'}]}


def test_strict_schema_and_invented_references():
    assert validate_response(response(),context())
    for mutate in [lambda x:x.update(status='approved'),lambda x:x['classifications'][0].update(instance='fake'),
                   lambda x:x['classifications'].clear(),lambda x:x['classifications'][0].update(evidence=['fake']),
                   lambda x:x['proposals'][0].update(operation='execute_shell')]:
        value=response();mutate(value)
        with pytest.raises(ValueError):validate_response(value,context())


class FakeProvider:
    name='local';endpoint='http://127.0.0.1/v1';model='test';calls=0
    def run(self,*args):
        self.calls+=1
        return json.dumps(response()),{'input_tokens':100,'output_tokens':20,'cost':0,'seconds':.01}


def test_three_pass_dependencies_human_review_and_restart(tmp_path):
    with AuditStore(tmp_path/'audit.sqlite') as s:
        p1=s.job(1,'first_task',context());p2=s.job(2,'first_task',context(),[p1]);p3=s.job(3,'first_task',context(),[p1,p2]);s.db.commit()
        provider=FakeProvider();report=run(s,provider,1)
        assert report['jobs']['done']==1 and report['proposals']['pending']==1
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(p2,)).fetchone()[0]=='pending'
        run(s,provider,2);assert s.db.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]==3
        proposal=s.db.execute('SELECT id FROM proposals LIMIT 1').fetchone()[0]
        with pytest.raises(ValueError):review(s,proposal,'approve','')
        review(s,proposal,'approve','actual human');assert s.report()['proposals']['approved']==1
        review(s,proposal,'edit','actual human',response()['proposals'][0]);assert s.db.execute('SELECT status FROM proposals WHERE id=?',(proposal,)).fetchone()[0]=='pending'
        assert s.db.execute('SELECT COUNT(*) FROM review_log').fetchone()[0]==2
        assert s.report()['llm_reviewed_jobs_by_scope']=={'first_task':3}


def test_inference_cache_and_paid_budget_are_explicit(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.job(2,'first_task',context());s.job(2,'other',context());s.db.commit()
        provider=FakeProvider();run(s,provider,1);run(s,provider,1,scope='other');assert provider.calls==1
        remote=Provider('https://api.deepseek.com/v1','deepseek-chat','deepseek',Path('not-opened.key'))
        with pytest.raises(ValueError,match='budget'):run(s,remote,1)
        assert remote.key_file==Path('not-opened.key')


def test_provider_rejects_remote_local_and_untrusted_remote():
    with pytest.raises(ValueError):Provider('https://example.com/v1','x')
    with pytest.raises(ValueError):Provider('https://example.com/v1','x','deepseek')


def test_resume_interrupted_job_and_failure_does_not_count_review(tmp_path):
    with AuditStore(tmp_path/'a.sqlite') as s:
        jid=s.job(2,'first_task',context());s.db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,));s.db.commit()
        class Invalid(FakeProvider):
            def run(self,*a):return '{}',{'input_tokens':10,'output_tokens':2,'cost':0,'seconds':.01}
        report=run(s,Invalid(),1)
        assert report['jobs']['failed']==1 and report['llm_reviewed_jobs_by_scope']=={}


def test_inventory_no_credentials_and_rebuild(tmp_path):
    from astralogue.audit.inventory import traverse
    source=tmp_path/'data/raw/test';source.mkdir(parents=True)
    (source/'TalkSentenceConfig.json').write_text(json.dumps([{'TalkSentenceID':1}]))
    (tmp_path/'DEEPSEEK.key').write_text('must never enter index')
    with AuditStore(tmp_path/'index.sqlite') as s:
        a=traverse(s,tmp_path);b=traverse(s,tmp_path)
        assert a['records_by_kind']==b['records_by_kind']=={'dialogue_catalog':1}
        assert s.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]==1


def test_ir_all_components_and_phase_unknown_retained(tmp_path):
    from astralogue.audit.inventory import traverse
    path=tmp_path/'data/staging';path.mkdir(parents=True)
    value={'ir_version':1,'metadata':{'source':'bound'},'nodes':[{'id':'a'}],'edges':[{'source':'a','target':'b'}],'texts':{'line':{'CHS':'fixture'}},'source_refs':[{'node':'a'}]}
    (path/'sample.ir.json').write_text(json.dumps(value))
    with AuditStore(tmp_path/'a.sqlite') as s:
        traverse(s,tmp_path)
        components={json.loads(r[0])['component'] for r in s.db.execute("SELECT payload FROM records WHERE kind='ir_representation'")}
        assert components==set(value)


def test_template_echo_is_not_semantic_review():
    value=response();value['classifications'][0]['uncertainty']='说明证据不足之处'
    with pytest.raises(ValueError,match='Template echo'):validate_response(value,context())


def test_paid_budget_refuses_before_request(tmp_path):
    class Paid(FakeProvider):
        name='deepseek';input_price=100;output_price=100
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.job(2,'first_task',context());s.db.commit()
        p=Paid();run(s,p,1,max_cost=.000001)
        assert p.calls==0 and s.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==0
