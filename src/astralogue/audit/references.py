"""Normalize exact, evidenced IDs to aliases; never guess missing references."""
from copy import deepcopy


def canonicalize(value,context):
    value=deepcopy(value);primary=context['instances'];bindings={**context.get('reference_instances',{}),**primary};scenes=context.get('scenes',{})
    def resolve(raw,allow_nodes=True,allow_scenes=False,primary_only=False):
        if not isinstance(raw,str):return raw
        domain=primary if primary_only else bindings
        if allow_nodes and raw in domain or allow_scenes and raw in scenes:return raw
        candidates=[]
        if allow_nodes:
            exact=[a for a,v in domain.items() if raw in {v.get('node'),v.get('id')}]
            preferred=[a for a in exact if a in primary]
            if len(preferred)==1:exact=preferred
            elif len(exact)>1 and all(domain[a].get('node')==raw for a in exact):exact=[sorted(exact)[0]]
            candidates+=exact
        if allow_scenes:candidates += [a for a,v in scenes.items() if v.get('id')==raw]
        return candidates[0] if len(candidates)==1 else raw
    for c in value['classifications']:
        c['instance']=resolve(c['instance'],primary_only=True)
        c['scenes']=[resolve(v,False,True) for v in c['scenes']]
    for p in value.get('proposals',[]):
        p['instances']=[resolve(v) for v in p['instances']]
        p['targets']=[resolve(v,True,True) for v in p['targets']]
        for diff in [p['before'],p['after']]:
            if isinstance(diff.get('candidate_phases'),list):diff['candidate_phases']=[resolve(v,False,True) for v in diff['candidate_phases']]
            for key in ['phase_id','phase','scene_id']:
                if isinstance(diff.get(key),str):diff[key]=resolve(diff[key],False,True)
    return value


def no_change(context,value):
    if context.get('review_intent')=='promote_research' or context.get('initial_case_review') or not context.get('parent_suggestion'):return False
    from .dedup import key
    return bool(value['proposals']) and all(key(context,p)==key(context,context['parent_suggestion']) for p in value['proposals'])
