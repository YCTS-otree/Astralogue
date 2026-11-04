"""Separate actual traversal, model submission, valid review and human acceptance."""
import json
from collections import Counter,defaultdict
from astralogue.audit.protocol import validate_response


def report(store):
    base=store.report();submitted=defaultdict(set);reviewed=defaultdict(set);unknown=defaultdict(set);scenes=Counter();categories=Counter()
    for row in store.db.execute('SELECT * FROM jobs'):
        if row['status']=='superseded':continue
        context=json.loads(row['context'])
        called=store.db.execute('SELECT 1 FROM calls WHERE job=?',(row['id'],)).fetchone()
        def identity(alias,value):return value.get('node') or value.get('record_id') or value.get('id') or row['id']+':'+alias
        if called:
            submitted[row['scope']].update(identity(k,v) for k,v in context['instances'].items())
        if row['status']!='done':continue
        try:value=validate_response(json.loads(row['result']),context)
        except ValueError:continue
        if row['pass']!=2:scenes[row['scope']]+=1;continue
        for c in value['classifications']:
            key=identity(c['instance'],context['instances'][c['instance']]);reviewed[row['scope']].add(key);categories[c['category']]+=1
            if c['category']=='UNKNOWN':unknown[row['scope']].add(key)
    base.update({'instances_submitted_to_llm':{k:len(v) for k,v in submitted.items()},
        'instances_with_valid_llm_review':{k:len(v) for k,v in reviewed.items()},'llm_undecidable_instances':{k:len(v) for k,v in unknown.items()},
        'scene_or_task_review_blocks':dict(scenes),'llm_categories':dict(categories),
        'ownership_check':store.setting('ownership_report'),
        'prologue_plan':[{k:v for k,v in p.items() if k in {'task','nodes'}} for p in store.setting('audit_plan') or []],
        'human_approved':store.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0],
        'published_pack_modified':False,'unreviewed_changes_applied':0})
    findings=store.setting('first_task_findings')
    if findings:base['first_task_findings']={k:v for k,v in findings.items() if k not in {'path','audit_edges'}}
    return base
