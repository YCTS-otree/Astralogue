"""One bounded association-review round before model drafts become applications."""
import json
from copy import deepcopy
from astralogue.model import digest
from astralogue.adapters.wiki import normalize


def signature(context,proposals):
    bindings={**context.get('reference_instances',{}),**context.get('instances',{})};nodes=set();texts=set();phases=set()
    for proposal in proposals:
        for alias in proposal['instances']:
            item=bindings.get(alias,{})
            if item.get('node'):nodes.add(item['node'])
            text=item.get('text','');text=text.get('CHS','') if isinstance(text,dict) else text
            if isinstance(text,str) and len(normalize(text))>=8:texts.add(normalize(text))
        after=proposal.get('after',{});phase_values=after.get('candidate_phases',[]) or [after.get('phase_id') or after.get('phase')]
        for alias in [v for v in phase_values if v]:
            phases.add(context.get('scenes',{}).get(alias,{}).get('id',alias))
    return nodes,texts,phases


def related(store,context,value):
    nodes,texts,phases=signature(context,value['proposals']);task=(context.get('task') or {}).get('title');result=[]
    for row in store.db.execute("SELECT * FROM proposals WHERE deleted_at IS NULL AND status NOT IN ('withdrawn','superseded','invalid_revision')"):
        payload=json.loads(row['payload']);ctx=payload['context'];other_nodes,other_texts,other_phases=signature(ctx,[payload['suggestion']]);reasons=[]
        if context.get('parent_proposal')==row['id']:reasons.append('本次返修的原申请')
        if nodes&other_nodes:reasons.append('相同执行节点')
        if task and task==(ctx.get('task') or {}).get('title'):
            if texts&other_texts:reasons.append('同任务相同长句，可能属于不同触发实例')
            if phases&other_phases:reasons.append('同任务同场景阶段，关联不代表冲突')
        left=context.get('evidence',{}).get('wiki',{});right=ctx.get('evidence',{}).get('wiki',{})
        if left.get('sha256') and left.get('sha256')==right.get('sha256') and left.get('source',{}).get('start') is not None and left.get('source',{}).get('start')==right.get('source',{}).get('start'):reasons.append('同版本同来源块')
        if context.get('source_unit_id') and context['source_unit_id']==ctx.get('source_unit_id'):reasons.append('相同来源块')
        if not reasons:continue
        bindings={**ctx.get('reference_instances',{}),**ctx.get('instances',{})}
        publication=store.db.execute('SELECT status FROM publications WHERE proposal=?',(row['id'],)).fetchone()
        result.append({'id':row['id'],'status':row['status'],'publication_status':publication[0] if publication else None,'reasons':reasons,
                       'suggestion':payload['suggestion'],'instances':{a:bindings[a] for a in payload['suggestion']['instances'] if a in bindings},
                       'context_hash':payload.get('context_hash'),'evidence':ctx.get('evidence',{}).get('wiki',{})})
    return result


def stage(store,row,context,value,provider):
    if context.get('related_review_pass') or not value['proposals']:return None
    applications=related(store,context,value)
    if not applications:return None
    next_context=deepcopy(context);next_context.update({'related_review_pass':True,'review_of_job':row['id'],'draft_response':value,
        'related_applications':applications,'feedback_provider':provider.name,
        'related_provider':{'model':provider.model,'endpoint':provider.endpoint,'input_price':getattr(provider,'input_price',None),'output_price':getattr(provider,'output_price',None),'revision':getattr(provider,'revision',None)},
        'pass_instructions':'这是额外且仅一次的关联复核：审查 draft_response 和 related_applications（包括已批准/发布申请）。核对重复、互补、冲突和触发上下文，不把相同文本误合并。尊重人工评论及原始证据；已批准内容不能自动覆盖。输出最终待人工审核的1–3份提案，中文说明关联及处理依据。无法确定时明确报告冲突或未知，不得编造。'})
    job=store.job(row['pass'],'human_feedback:related:'+digest([row['id'],applications])[:24],next_context)
    store.db.execute('UPDATE review_comments SET job=? WHERE job=?',(job,row['id']))
    return job
