"""Fresh source-scoped review rounds that keep passed decisions and packs."""
import json,time
from pathlib import Path
from astralogue.model import canonical,digest
from .navigation import catalog,request_source
from .feedback import enrich_context


def restart(store):
    store.setting('run_state','paused')
    rows=list(store.db.execute("SELECT * FROM proposals WHERE status!='approved'"))
    tasks={(json.loads(r['payload'])['context'].get('task') or {}).get('title') for r in rows};tasks.discard(None)
    approved=[json.loads(r[0]) for r in store.db.execute("SELECT payload FROM proposals WHERE status='approved'")]
    protected_nodes=set();protected_sources=set()
    for p in approved:
        ctx=p['context'];bindings={**ctx.get('reference_instances',{}),**ctx.get('instances',{})}
        protected_nodes.update(bindings[a].get('node') for a in p['suggestion']['instances'] if a in bindings)
        proof=ctx.get('evidence',{}).get('wiki',{})
        if proof.get('sha256') and proof.get('source',{}).get('start') is not None:protected_sources.add((proof['sha256'],proof['source']['start']))
    protected_nodes.discard(None);now=time.time();round_id='review-round:'+digest([now,tasks.__repr__()])[:20]
    with store.db:
        store.db.execute("UPDATE jobs SET status='cancelled',error='用户清理未通过申请并重新审查，旧任务不再提交结果' WHERE status IN ('pending','running','failed')")
        for row in rows:
            store.db.execute('UPDATE proposals SET deleted_at=COALESCE(deleted_at,?) WHERE id=?',(now,row['id']))
        store.db.execute('INSERT INTO review_log(proposal,action,reviewer,at,before,after) VALUES(?,?,?,?,?,?)',
            ('*','restart_unapproved_review','用户授权',now,canonical({'unapproved_count':len(rows)}),canonical({'round':round_id,'approved_kept':len(approved),'published_unchanged':True})))
    store.setting('review_round',round_id)
    units=list({u['id']:u for u in catalog() if u['task'] in tasks}.values());has_folds={(u['task'],u['section']) for u in units if u['part']['kind']!='section'}
    cases=[];skipped=[]
    for unit in units:
        if unit['part']['kind']=='section' and (unit['task'],unit['section']) in has_folds:continue
        if (unit['sha256'],unit['part']['source']['start']) in protected_sources:skipped.append(unit['id']);continue
        result=request_source(store,unit['id'],'source_parse','用户授权的重新解析')
        pid=result['proposal'];row=store.db.execute('SELECT payload FROM proposals WHERE id=?',(pid,)).fetchone();payload=json.loads(row[0]);ctx=payload['context']
        selected={v.get('node') for v in ctx['instances'].values() if v.get('node')}
        if selected and selected<=protected_nodes:
            with store.db:store.db.execute('UPDATE proposals SET deleted_at=? WHERE id=?',(now,pid))
            skipped.append(unit['id']);continue
        ctx['initial_case_review']=True
        ctx['parent_proposal']=pid;ctx['parent_suggestion']=payload['suggestion'];ctx['feedback_provider']='local';ctx['require_chinese_notes']=True
        ctx['review_case_id']=unit['id'];ctx['review_round']=round_id
        enrich_context(store,ctx)
        bindings={**ctx.get('reference_instances',{}),**ctx['instances']}
        from astralogue.adapters.wiki import normalize
        from .presentation import text
        raw=normalize(unit['text'])
        ctx['scope_aliases']=list(ctx['instances'])+[a for a,v in bindings.items() if len(normalize(text(v.get('text'))))>=6 and normalize(text(v.get('text'))) in raw]
        ctx['read_only_aliases']=[a for a,v in bindings.items() if v.get('node') in protected_nodes]
        ctx['evidence']['rerun_authorization']={'kind':'user_authorized_rerun_not_game_fact','scope':unit['part']['label'],'approved_content_read_only':True}
        ctx['pass_instructions']='这是用户授权的全新复审。只审查当前来源块，保留已有通过内容。read_only_aliases 仅作上下文，不得作为修改对象。按原始结构判断主动互动、首次/再次访问或真实选项，中文说明；每个来源块提交1份主要申请，确有不同对象或独立修改时最多3份。不要把同一对象的连续回应拆成重复申请。不得生成已通过内容的重复请求。证据不足提交明确缺口，不要笼统重复整个任务。'
        job=store.job(2,'human_feedback:rerun:'+digest([round_id,unit['id']])[:24],ctx)
        with store.db:
            store.db.execute("UPDATE proposals SET status='awaiting_revision' WHERE id=?",(pid,))
            store.db.execute('INSERT INTO review_comments(proposal,reviewer,comment,action,job,at) VALUES(?,?,?,?,?,?)',
                (pid,'用户授权重新审查','对本来源块重新运行解析器和本地模型；通过的内容保持不变。','rerun',job,time.time()))
        cases.append({'source':unit['id'],'label':unit['part']['label'],'task':unit['task'],'proposal':pid,'job':job})
    report={'round':round_id,'old_unapproved_removed':len(rows),'approved_kept':len(approved),'cases':cases,'approved_sources_skipped':len(skipped),'published_unchanged':True,'provider':'local'}
    store.setting('latest_review_restart',report);store.setting('run_state','running');return report
