"""Machine flags are separate from human review decisions and source truth."""
from collections import defaultdict
import json


def check(store):
    store.db.execute('CREATE TABLE IF NOT EXISTS proposal_flags(proposal TEXT,flag TEXT,other TEXT,PRIMARY KEY(proposal,flag,other))')
    store.db.execute('DELETE FROM proposal_flags');by_node=defaultdict(list)
    baseline=store.setting('first_task_findings');main={n['node'] for n in baseline['path']} if baseline else None
    def flag(pid,name,other=''):
        store.db.execute('INSERT OR IGNORE INTO proposal_flags VALUES(?,?,?)',(pid,name,other))
    for row in store.db.execute('SELECT id,payload FROM proposals'):
        payload=json.loads(row['payload']);p=payload['suggestion'];ctx=payload['context'];bindings={**ctx.get('reference_instances',{}),**ctx['instances']}
        for alias in p['instances']:
            node=bindings.get(alias,{}).get('node')
            if node:
                by_node[node].append((row['id'],p['operation']))
                if main is not None and p['operation']=='move_to_optional_interaction' and node not in main:flag(row['id'],'not_on_known_first_task_default_path')
            elif p['operation']=='move_to_optional_interaction':flag(row['id'],'source_instance_requires_explicit_execution_binding')
        if p['operation']=='move_to_optional_interaction':
            phases=p['after'].get('candidate_phases',[]) or ([p['after']['phase_id']] if p['after'].get('phase_id') else [x for x in p['targets'] if x in ctx.get('scenes',{})])
            if len(phases)!=1:flag(row['id'],'phase_needs_human_selection')
    for items in by_node.values():
        for pid,op in items:
            for other,otherop in items:
                if pid==other:continue
                if op==otherop:flag(pid,'overlapping_candidate_not_additional_recovery',other)
                elif {op,otherop}=={'move_to_optional_interaction','mark_as_required'}:flag(pid,'opposed_content_role_proposals',other)
    store.db.commit()
    result=dict(store.db.execute('SELECT flag,COUNT(*) FROM proposal_flags GROUP BY flag'));store.setting('proposal_consistency',result);return result
