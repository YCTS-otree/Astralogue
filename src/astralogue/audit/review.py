"""Human-only decisions and a bounded Community Patch conversion."""
from datetime import datetime,timezone
import json
import time
from astralogue.model import canonical,digest
from .protocol import RESPONSE_SCHEMA,validate_schema


def review(store,pid,action,reviewer,suggestion=None):
    if action not in {'approve','reject','defer','edit','acknowledge'} or not reviewer.strip():raise ValueError('Explicit reviewer and decision required')
    with store.db:
        if not store.db.in_transaction:store.db.execute('BEGIN IMMEDIATE')
        row=store.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
        if row is None:raise ValueError('Unknown proposal')
        if row['deleted_at'] is not None:raise ValueError('申请已从列表删除，历史只读；请重新发起审查')
        if row['status']=='withdrawn':raise ValueError('所属研究已撤销，请从原研究重新申请')
        before=row['payload'];payload=json.loads(before)
        if suggestion is not None:
            validate_schema(suggestion,RESPONSE_SCHEMA['properties']['proposals']['items'])
            ctx=payload['context']
            aliases=set(ctx['instances'])|set(ctx.get('reference_instances',{}))
            if set(suggestion['instances'])-aliases or set(suggestion['targets'])-(aliases|set(ctx.get('scenes',{}))) or set(suggestion['evidence'])-set(ctx['evidence']):raise ValueError('Invented proposal reference')
            payload['suggestion']=suggestion
            if action!='edit':raise ValueError('Edited proposal must be reviewed again separately')
        status={'approve':'approved','reject':'rejected','defer':'deferred','edit':'pending','acknowledge':'acknowledged'}[action]
        store.db.execute('UPDATE proposals SET payload=?,status=?,reviewer=?,reviewed_at=? WHERE id=?',(canonical(payload),status,reviewer,time.time(),pid))
        store.db.execute('INSERT INTO review_log(proposal,action,reviewer,at,before,after) VALUES(?,?,?,?,?,?)',(pid,action,reviewer,time.time(),before,canonical(payload)))


def export_patch(store,pid,bundle):
    row=store.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
    if not row or row['status']!='approved':raise ValueError('Human approval required')
    payload=json.loads(row['payload']);p=json.loads(json.dumps(payload['suggestion']));ctx=payload['context']
    if digest(ctx)!=payload['context_hash']:raise ValueError('Proposal evidence context changed; review is stale')
    if not p['after'].get('candidate_phases') and not p['after'].get('phase_id'):
        target_phases=[x for x in p['targets'] if x in ctx.get('scenes',{})]
        if target_phases:p['after']['candidate_phases']=target_phases
    for field in ['candidate_phases','phase_id']:
        value=p['after'].get(field)
        if value is None:continue
        phases=value if isinstance(value,list) else [value];resolved=[]
        for phase in phases:
            if phase not in ctx.get('scenes',{}):raise ValueError('Unknown phase reference; review cannot invent a scene')
            resolved.append(ctx['scenes'][phase].get('id',phase))
        p['after'][field]=resolved if isinstance(value,list) else resolved[0]
    bindings={**ctx.get('reference_instances',{}),**ctx['instances']}
    sources=[bindings[a].get('node') for a in p['instances']]
    if not sources or any(x is None for x in sources):raise ValueError('Proposal is not bound to executable nodes')
    nodes={n.id:n for n in bundle.nodes}
    if any(x not in nodes for x in sources):raise ValueError('Stale node reference')
    evidence=[{'id':k,'uri':'audit-evidence:'+digest(ctx['evidence'][k]),'record':ctx['evidence'][k]} for k in p['evidence']]
    info=bundle.metadata['narrative']
    graph=ctx['evidence'].get('graph',{})
    if graph.get('source_hashes')!=info.get('source_hashes'):raise ValueError('Upstream resource hashes changed; review is stale')
    provenance={'proposal':pid,'origin':payload.get('origin'),'context_hash':payload['context_hash'],'job':row['job']}
    if row['job']:
        call=store.db.execute('SELECT provider,model,input_tokens,output_tokens,metadata FROM calls WHERE job=? AND error IS NULL ORDER BY id DESC LIMIT 1',(row['job'],)).fetchone()
        if call:
            metadata=json.loads(call['metadata']);provenance.update({'provider':call['provider'],'model':call['model'],'model_revision':metadata.get('model_revision'),
                'prompt_version':metadata.get('prompt_version'),'input_tokens':call['input_tokens'],'output_tokens':call['output_tokens']})
    return {'patch_version':1,'id':'audit:'+pid,'status':'reviewed','game':info['game'],'game_version':info['game_version'],'audit_origin':provenance,
        'source_hashes':info['source_hashes'],'evidence':evidence,
        'review':{'reviewer':row['reviewer'],'reviewed_at':datetime.fromtimestamp(row['reviewed_at'],timezone.utc).isoformat(),'evidence':[e['id'] for e in evidence]},
        'operations':[{'op':'narrative_audit','source':sources[0],'nodes':sources,
            'before_hashes':{nid:digest(nodes[nid].__dict__) for nid in sources},'suggestion':p,
            'evidence':[e['id'] for e in evidence],'reader_only':True}],
        'audit_note':'Human-approved Reader review, never GAME_VERIFIED; control changes require audited reconstruction compiler'}
