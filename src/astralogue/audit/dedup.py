"""Exact proposal identity: remarks do not create another review application."""
import json
from astralogue.model import digest


def key(context,proposal):
    bindings={**context.get('reference_instances',{}),**context.get('instances',{})}
    nodes=sorted({bindings[a].get('node') for a in proposal['instances'] if a in bindings and bindings[a].get('node')})
    source=context.get('review_case_id') or context.get('source_unit_id')
    fallback={'task':context.get('task'),'chapter':context.get('chapter'),'wiki':context.get('evidence',{}).get('wiki'),'instances':[bindings.get(a,{}) for a in sorted(proposal['instances'])]}
    scope=nodes or [source or digest(fallback)]
    def normalize_diff(value,field=''):
        if isinstance(value,list):return [normalize_diff(v,field) for v in value]
        if isinstance(value,dict):return {k:normalize_diff(v,k) for k,v in value.items()}
        if isinstance(value,str):
            if field in {'phase','phase_id','scene_id','candidate_phases'}:return context.get('scenes',{}).get(value,{}).get('id',value)
            if field in {'node','nodes','source','target','source_node','target_node','default_path_nodes'}:return bindings.get(value,{}).get('node',bindings.get(value,{}).get('id',value))
        return value
    return digest([scope,proposal['operation'],normalize_diff(proposal['after'])])


def existing(store,context,proposal):
    wanted=key(context,proposal)
    for row in store.db.execute("SELECT id,payload FROM proposals WHERE deleted_at IS NULL AND status IN ('pending','approved')"):
        payload=json.loads(row['payload'])
        if key(payload['context'],payload['suggestion'])==wanted:return row['id']
    return None
