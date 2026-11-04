"""Exact proposal identity: remarks do not create another review application."""
import json
from astralogue.model import digest


def key(context,proposal):
    bindings={**context.get('reference_instances',{}),**context.get('instances',{})}
    nodes=sorted({bindings[a].get('node') for a in proposal['instances'] if a in bindings and bindings[a].get('node')})
    source=context.get('review_case_id') or context.get('source_unit_id')
    fallback={'task':context.get('task'),'chapter':context.get('chapter'),'wiki':context.get('evidence',{}).get('wiki'),'instances':[bindings.get(a,{}) for a in sorted(proposal['instances'])]}
    scope=nodes or [source or digest(fallback)]
    return digest([scope,proposal['operation'],proposal['after']])


def existing(store,context,proposal):
    wanted=key(context,proposal)
    for row in store.db.execute("SELECT id,payload FROM proposals WHERE deleted_at IS NULL AND status IN ('pending','approved')"):
        payload=json.loads(row['payload'])
        if key(payload['context'],payload['suggestion'])==wanted:return row['id']
    return None
