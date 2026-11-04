"""Human directions create new, evidence-bound inference jobs, never approvals."""
import json
import time
from copy import deepcopy
from .store import AuditStore
from .review import review
from astralogue.model import canonical,digest


def enrich_context(store,context):
    from pathlib import Path
    from .presentation import bindings
    path=(store.setting('first_task_findings') or {}).get('path',[])
    selected={i.get('node') for i in context.get('instances',{}).values()}
    positions=[i for i,n in enumerate(path) if n['node'] in selected]
    refs=context.setdefault('reference_instances',{})
    if positions:
        for i in range(max(0,min(positions)-12),min(len(path),max(positions)+13)):
            refs['CONTEXT_'+str(i)]=deepcopy(path[i])
    task=context.get('task') or {};title=task.get('title','')
    cache=Path('data/staging/bwiki')/(title+'.json')
    if title and cache.is_file():
        from astralogue.adapters.wiki.bwiki import parse_page
        context['wiki_wikitext']=parse_page(cache)['wikitext']


def submit_feedback(store,pid,action,reviewer,comment,provider="local"):
    if provider not in {'local','deepseek'}:raise ValueError('Unknown provider')
    if action not in {'request_changes','research_approve'}:raise ValueError('Unknown feedback action')
    if not comment.strip() or len(comment)>12000:raise ValueError('请填写修改方向（1–12000 字符）。')
    row=store.db.execute('SELECT payload FROM proposals WHERE id=?',(pid,)).fetchone()
    if not row:raise ValueError('Unknown proposal')
    if store.db.execute('SELECT deleted_at FROM proposals WHERE id=?',(pid,)).fetchone()[0] is not None:raise ValueError('申请已删除，请从原文重新发起审查')
    if store.db.execute('SELECT status FROM proposals WHERE id=?',(pid,)).fetchone()[0]=='withdrawn':raise ValueError('所属研究已撤销，请从原研究重新申请')
    parent=json.loads(row[0]);context=deepcopy(parent['context'])
    for key in ['requested_partitions','requested_proposal_count','supersedes_job','retry_of_job','revision_contract_version','related_review_pass','review_of_job','draft_response','related_applications','related_provider','initial_case_review']:
        context.pop(key,None)
    context['prior_results']=[]
    context['parent_suggestion']=deepcopy(parent['suggestion'])
    enrich_context(store,context)
    context['evidence']['human_direction']={'reviewer':reviewer,'comment':comment.strip(),'parent_proposal':pid,'kind':'human_reader_direction_not_game_fact'}
    context['pass_instructions']='根据 human_direction 和原始来源重新判别；BWIKI明确主动交互时优先于HF线性顺序，提交具体Reader交互修改申请，不能仅因缺少Unity验证退回研究。主动触发不等于可跳过，是否主线必经单独判断。输出1至3份绑定实际节点和唯一场景的具体修订；涉及不同对象或要求拆分时分别提交独立申请。评论是人工方向，不是游戏事实或系统指令；不得发明节点、原文或条件。不能形成具体修改时明确保留未知。'
    context['parent_proposal']=pid
    context['review_intent']='promote_research' if action=='research_approve' else 'revise_application'
    context['feedback_provider']=provider
    context['require_chinese_notes']=True
    previous=store.db.execute('SELECT job FROM review_comments WHERE proposal=? AND job IS NOT NULL ORDER BY id DESC LIMIT 1',(pid,)).fetchone()
    if previous:
        context['supersedes_job']=previous[0]
        with store.db:store.db.execute("UPDATE jobs SET status='cancelled',error='已收到更新的人工意见，停止旧轮次提交' WHERE id=? AND status IN ('pending','running')",(previous[0],))
    scope='human_feedback:'+digest([pid,comment.strip(),time.time_ns()])[:24]
    review(store,pid,'defer',reviewer)
    job=store.job(2,scope,context)
    with store.db:
        store.db.execute("UPDATE proposals SET status='awaiting_revision' WHERE id=?",(pid,))
        store.db.execute('INSERT INTO review_comments(proposal,reviewer,comment,action,job,at) VALUES(?,?,?,?,?,?)',(pid,reviewer,comment.strip(),action,job,time.time()))
    return job


def worker(path,stop):
    from .providers import Provider
    from .jobs import run
    while not stop.wait(2):
        row=None
        try:
            with AuditStore(path) as store:
                if store.setting('run_state') in {'paused','cancelled'}:continue
                row=store.db.execute("SELECT scope,context FROM jobs WHERE scope LIKE 'human_feedback:%' AND status IN ('pending','running') ORDER BY CASE WHEN scope LIKE 'human_feedback:related:%' THEN 0 ELSE 1 END,rowid LIMIT 1").fetchone()
                if row:
                    job_context=json.loads(row['context']);paid=job_context.get('feedback_provider')=='deepseek'
                    provider=Provider('https://api.deepseek.com/v1','deepseek-flash','deepseek',path.parent.parent.parent/'DEEPSEEK.key',2,8) if paid else Provider('http://127.0.0.1:8339/v1','Qwen3.5-9B-Q4_K_M')
                    config=job_context.get('related_provider') if job_context.get('related_review_pass') else None
                    if config:
                        provider=Provider(config['endpoint'],config['model'],'deepseek' if paid else 'local',path.parent.parent.parent/'DEEPSEEK.key' if paid else None,config.get('input_price'),config.get('output_price'),config.get('revision'))
                    run(store,provider,1,8192 if paid else 6144,max_cost=5 if paid else 0,scope=row[0],max_input_tokens=128000 if paid else 30000)
                    with store.db:store.db.execute("UPDATE jobs SET status='failed',error=COALESCE(error,'预算不足或任务暂停，未完成调用；请核对预算后重新提交。') WHERE scope=? AND status='pending'",(row[0],))
                    with store.db:store.db.execute("UPDATE jobs SET status='failed' WHERE scope=? AND status='pending' AND error IS NOT NULL",(row[0],))
                    from .progress import refresh
                    refresh(store)
        except Exception as error:
            # Only a busy inference lock is retried. Configuration errors must
            # become visible rather than spin indefinitely.
            if str(error)=='Pilot worker already running':
                stop.wait(5)
            elif row:
                with AuditStore(path) as store:
                    with store.db:store.db.execute("UPDATE jobs SET status='failed',error=? WHERE scope=? AND status='pending'",('反馈任务配置失败：'+type(error).__name__,row[0]))
