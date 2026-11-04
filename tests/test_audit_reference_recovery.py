import json
import pytest
from astralogue.audit.protocol import validate_response
from test_audit import context,response


def test_exact_real_ids_are_canonicalized_not_guessed():
    ctx=context();ctx['reference_instances']={'CONTEXT_1':{'node':'real-node'}}
    value=response();p=value['proposals'][0];p['targets']=['real-node','real-phase'];p['after']['candidate_phases']=['real-phase']
    value['classifications'][0]['instance']='real-node'
    result=validate_response(value,ctx)
    assert result['proposals'][0]['targets']==['a','phase']
    assert result['proposals'][0]['after']['candidate_phases']==['phase']
    assert result['classifications'][0]['instance']=='a'
    value['proposals'][0]['targets']=['invented-node']
    with pytest.raises(ValueError,match='invented-node'):validate_response(value,ctx)


def test_research_promotion_may_confirm_existing_plan():
    from astralogue.audit.references import no_change
    ctx=context();ctx['parent_proposal']='research';value=response();ctx['parent_suggestion']=value['proposals'][0]
    ctx['review_intent']='promote_research'
    assert validate_response(value,ctx) and not no_change(ctx,value)
    ctx['review_intent']='revise_application'
    assert no_change(ctx,value)


def test_unchanged_revision_is_a_result_not_error_or_duplicate(tmp_path):
    from astralogue.audit.store import AuditStore
    from astralogue.audit.jobs import run
    from test_audit import FakeProvider
    from astralogue.model import canonical
    ctx=context();ctx['parent_proposal']='parent';ctx['review_intent']='revise_application';ctx['related_review_pass']=True
    ctx['parent_suggestion']=response()['proposals'][0]
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.db.execute("INSERT INTO proposals(id,payload,status) VALUES(?,?,'awaiting_revision')",('parent',canonical({'context':ctx,'suggestion':ctx['parent_suggestion']})))
        job=s.job(2,'human_feedback:test',ctx)
        s.db.execute("INSERT INTO review_comments(proposal,job,action) VALUES('parent',?,'request_changes')",(job,));s.db.commit()
        run(s,FakeProvider(),1,scope='human_feedback:test')
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]=='no_change'
        assert s.db.execute("SELECT status FROM proposals WHERE id='parent'").fetchone()[0]=='revision_no_change'
        assert s.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1

def test_recovery_reuses_paid_result_without_calling_api(tmp_path):
    from astralogue.audit.store import AuditStore
    from astralogue.audit.jobs import run
    from astralogue.audit.providers import Provider
    from astralogue.model import canonical
    ctx=context();ctx.update(parent_proposal='parent',review_intent='promote_research',recovery_response=json.dumps(response()),recovery_call=42)
    ctx['parent_suggestion']=response()['proposals'][0]
    class NoNetwork(Provider):
        def run(self,*a):raise AssertionError('paid generation must not repeat')
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.setting('deepseek_budget_cny',5);s.setting('deepseek_committed_upper_cny',1)
        s.db.execute("INSERT INTO proposals(id,payload,status) VALUES(?,?,'awaiting_revision')",('parent',canonical({'context':ctx,'suggestion':ctx['parent_suggestion']})));s.db.commit()
        job=s.job(2,'human_feedback:recover',ctx);s.db.commit()
        run(s,NoNetwork('https://api.deepseek.com/v1','deepseek-flash','deepseek',input_price=2,output_price=8),1,max_cost=5,scope='human_feedback:recover')
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]=='done'
        assert s.setting('deepseek_committed_upper_cny')==1
        extra=json.loads(s.db.execute("SELECT context FROM jobs WHERE scope LIKE 'human_feedback:related:%'").fetchone()[0])
        assert 'recovery_response' not in extra and extra['related_review_pass']


def test_structural_diff_known_label_resolves_to_bound_node():
    ctx=context();ctx['instances']['a']['label']='调查楼梯'
    value=response();value['proposals'][0]['before']={'default_path_nodes':['调查楼梯']}
    result=validate_response(value,ctx)
    assert result['proposals'][0]['before']['default_path_nodes']==['a']
    value['proposals'][0]['before']['default_path_nodes']=['不存在的楼梯']
    with pytest.raises(ValueError):validate_response(value,ctx)


def test_source_binding_ignores_formatting_whitespace_but_preserves_ambiguity(tmp_path):
    from astralogue.audit.source_binding import bind_sources
    from astralogue.audit.store import AuditStore
    from astralogue.compiler import compile_story
    from test_audit_cleanup import fixture
    b,_=fixture();b.metadata['story_arcs']['reader']={'plan':{'tasks':[{'title':'任务'}]}}
    b.texts['o1']['CHS']='光栅拦住去路。\n\n再次调查你不能通过！'
    path=tmp_path/'p.storypack';compile_story(b,path)
    def ctx():return {'task':{'title':'任务'},'instances':{'SOURCE':{'id':'source','kind':'wiki_source_instance','label':'调查楼梯','text':'光栅拦住去路。<br>\n{{颜色|描述|再次调查}}<br>你不能通过！'}}}
    with AuditStore(tmp_path/'a.sqlite') as store:
        store.setting('publication_pack',str(path));context=ctx();bind_sources(store,context)
        assert context['instances']['SOURCE']['node']=='o1'
        assert context['instances']['SOURCE']['source_raw_text'].startswith('光栅')
        b.texts['o2']['CHS']=b.texts['o1']['CHS'];compile_story(b,path,force=True)
        ambiguous=ctx();bind_sources(store,ambiguous);assert not ambiguous['instances']['SOURCE'].get('node')
