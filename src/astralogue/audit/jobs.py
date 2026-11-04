"""Scene-context blocks and three dependent passes, with bounded persistent execution."""
from collections import defaultdict
from pathlib import Path
import json
import time
from astralogue.model import canonical,digest,load_json,file_hash
from astralogue.storypack import StoryPack
from astralogue.adapters.wiki.bwiki import parse_page
from astralogue.adapters.wiki.scenes import classify_page
from .protocol import PROMPT_VERSION,messages,validate_response,constrained_schema


def prepare(store,root:Path,pack_path:Path,block_size=8):
    if not 1<=block_size<=32:raise ValueError('Block size must be 1..32')
    with StoryPack(pack_path) as pack:
        bundle=pack.bundle();mid=next(iter(pack.metadata['story_arcs']));arc=pack.metadata['story_arcs'][mid]
        nodes={n.id:n for n in bundle.nodes};edges=defaultdict(list)
        for e in bundle.edges:edges[e.source].append(e.__dict__)
        all_proposals=[]
        for task,t in enumerate(arc['plan']['tasks']):
            scope='first_task' if task==0 else 'prologue'
            paths=[root/'data/staging/bwiki'/(t['title']+'.json')]
            # Existing queue gives exact title aliases and source identities.
            queue=root/'data/staging/bwiki-pilot/queue.sqlite'
            if queue.exists():
                import sqlite3
                c=sqlite3.connect(queue.resolve().as_uri()+'?mode=ro',uri=True)
                for title,cache in c.execute('SELECT title,cache FROM pages WHERE cache IS NOT NULL'):
                    if title.replace('•','·')==t['title'].replace('•','·'):paths.append(queue.parent/cache)
                c.close()
            page=next((p for p in paths if p.exists()),None)
            wiki=parse_page(page) if page else None
            sections=classify_page(wiki)['sections'] if wiki else []
            if page:
                from astralogue.audit.inventory import kind_for
                logical=page.relative_to(root).as_posix();sha=file_hash(page);sid=digest([logical,sha])
                store.db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?)',(sid,logical,sha,kind_for(page),0,'context_only',None))
                for section in sections:
                    for interaction in section['interactions']:
                        store.record('wiki_interaction_instance',interaction['id'],interaction,sid,
                                     'wikitext:'+str(interaction['source']['start']),scope)
            scenes={str(i):{'id':s['id'],'title':s['title'],'start':s['start'],'end':s['end']} for i,s in enumerate(sections)}
            hfpath=root/'data/external/hf-trailblaze'/t['hf'];hf=load_json(hfpath)
            evidence={'wiki':{'path':str(page.relative_to(root)),'sha256':file_hash(page),'revision':wiki['revision_id']} if page else {'missing':True},
                      'hf':{'path':t['hf'],'sha256':file_hash(hfpath),'path_coverage':'first-option transcript, incomplete branches'},
                      'graph':{'pack_id':pack.metadata['pack_id'],'source_hashes':pack.metadata.get('narrative',{}).get('source_hashes',{})}}
            candidates=[n for n in bundle.nodes if n.mission==mid and n.data.get('task')==task]
            # Stable presentation order for audit only; edges carry actual flow.
            candidates.sort(key=lambda n:(n.data.get('hf_index',10**9),n.id))
            def view(n):
                return {'node':n.id,'kind':n.kind,'text':bundle.texts.get(n.text,{}),'speaker':bundle.texts.get(n.speaker,{}),
                        'data':n.data,'outgoing':[{**e,'option_text':bundle.texts.get(e.get('text'),{})} for e in edges[n.id]], 'existing_classification':'UNKNOWN'}
            overview={'task':t,'chapter':arc['plan']['title'],'evidence':evidence,'scenes':scenes,
                      'instances':{'task':{'title':t['title'],'kind':'task_structure'}},
                      'wiki_wikitext':wiki['wikitext'] if wiki else None,'hf_transcript':hf['story'],
                      'pass_instructions':'Pass 1: identify required steps, phases, optional and conditional interactions; do not classify all transcript entries as required.'}
            p1parts=[]
            for section in sections or [None]:
                local={**overview,'audit_plan_version':3}
                if section:
                    local['wiki_wikitext']=wiki['wikitext'][section['start']:section['end']]
                    local['hf_transcript']={'full_source_retained':str(hfpath),'sha256':file_hash(hfpath),'scope':'scene structure pass; full transcript is used in instance pass'}
                    local['instances']={'phase':{'id':section['id'],'title':section['title'],'kind':'scene_structure'}}
                p1parts.append(store.job(1,scope,local))
            jobs=[]
            for offset in range(0,len(candidates),block_size):
                chunk=candidates[offset:offset+block_size]
                context={'task':t,'chapter':arc['plan']['title'],'evidence':evidence,'scenes':scenes,
                    'instances':{str(i):view(n) for i,n in enumerate(chunk)},
                    'overlap_before':[view(n) for n in candidates[max(0,offset-2):offset]],
                    'overlap_after':[view(n) for n in candidates[offset+len(chunk):offset+len(chunk)+2]],
                    'wiki_wikitext':wiki['wikitext'] if wiki else None,
                    'hf_transcript':hf['story'],
                    'pass_instructions':'Pass 2: classify EVERY instance, especially optional content already present in current default/main path. Use outgoing edges, never this presentation order as execution evidence.'}
                context['audit_plan_version']=3
                jobs.append(store.job(2,scope,context,p1parts))
            wiki_count=0;source_views={}
            for section in sections:
                for offset in range(0,len(section['interactions']),4):
                    items=section['interactions'][offset:offset+4];wiki_count+=len(items)
                    source_views.update({'W'+str(len(source_views)+i):{'id':v['id'],'kind':'wiki_source_instance','label':v['label'],'source':v['source']} for i,v in enumerate(items)})
                    local={**overview,'audit_plan_version':3,'wiki_wikitext':wiki['wikitext'][section['start']:section['end']],
                        'hf_transcript':{'path':t['hf'],'hash':file_hash(hfpath),'scope':'source-only interaction audit; executable instances audited in separate blocks'},
                        'instances':{str(i):{'id':v['id'],'kind':'wiki_source_instance','label':v['label'],'text':{'CHS':v['raw']},
                                           'source':v['source'],'current_kind':v['kind'],'availability':v['availability']} for i,v in enumerate(items)},
                        'pass_instructions':'Pass 2: review every Wiki source interaction, including investigations, optional folds, stage directions and unconnected objects. A fold is not automatically optional. Investigation can be required.'}
                    jobs.append(store.job(2,scope,local,p1parts))
            p3=store.job(3,scope,{**overview,'audit_plan_version':3,'reference_instances':{**{'N'+str(i):view(n) for i,n in enumerate(candidates)},**source_views},
                'known_world_state':'UNKNOWN; Reader progress is not original game world state',
                'mission_control_records':[{k:r[k] for k in ['id','category','chapter','prerequisites','prerequisite_operation','finish_submissions','provenance','submissions'] if k in r}
                                           for r in arc['plan'].get('internal_records',[]) if r.get('id') in t['main_ids']],
                'pass_instructions':'Pass 3: reconcile all prior persisted classifications and conflicts, cross-block boundaries and graph differences. Classify only the task instance; proposals may refer to reference_instances N*/W*. Prior results contain persistent alias-to-object bindings. Retain contradictions, never merge them silently.'},[*p1parts,*jobs])
            all_proposals.append({'task':t['title'],'nodes':len(candidates),'wiki_source_instances':wiki_count,'pass1':p1parts,'pass2':jobs,'pass3':p3})
        store.db.commit()
    store.setting('audit_plan',all_proposals);return all_proposals


def queue_unassigned(store,size=64):
    batch=[];count=0
    texts={}
    for row in store.db.execute("SELECT payload FROM records WHERE kind='archive:texts'"):
        value=json.loads(row[0]);texts.setdefault(str(value['id']),[]).append({'text':value.get('text'),'speaker':value.get('speaker'),'lang':value.get('lang')})
    if not store.setting('background_text_context_v1'):
        store.db.execute("UPDATE jobs SET status='superseded' WHERE scope='unassigned' AND status='pending'")
    rows=list(store.db.execute("SELECT id,logical,payload FROM records WHERE kind='dialogue_catalog' AND scope='global' ORDER BY logical"))
    for row in rows:
        item=dict(row);original=json.loads(item['payload']);sid=str(original.get('TalkSentenceID'))
        item['text_candidates']=texts.get(sid,[]);batch.append(item)
        if len(batch)==size:
            _background(store,batch);count+=1;batch=[]
            if count%100==0:store.db.commit()
    if batch:_background(store,batch);count+=1
    store.db.commit();store.setting('background_text_context_v1',True);return count


def _background(store,batch):
    store.job(2,'unassigned',{'task':None,'chapter':None,'scenes':{},'evidence':{'catalog':{'records':[r['id'] for r in batch]}},
        'instances':{str(i):{'record_id':r['id'],'catalog':json.loads(r['payload']),'text_candidates':r.get('text_candidates',[]),'ownership':'UNKNOWN'} for i,r in enumerate(batch)},
        'pass_instructions':'Background triage only: catalog proximity does NOT prove dialogue order or prologue membership; unknown source ownership remains UNKNOWN.'})


def run(store,provider,max_batches,max_tokens=2048,max_cost=0.0,scope='first_task',max_input_tokens=24000,failed_only=False,pass_number=None):
    if max_batches<1:raise ValueError('Explicit positive batch budget required')
    if provider.name=='deepseek' and (max_cost<=0 or provider.input_price is None or provider.output_price is None):raise ValueError('Paid provider requires explicit cost budget and per-million prices')
    from astralogue.adapters.wiki.pilot import single_instance
    with single_instance(store.path.with_suffix('.worker.lock')):
        with store.db:store.db.execute("UPDATE jobs SET status='pending',error='Recovered interrupted inference' WHERE status='running'")
        store.setting('run_state','running');done=0;spent=0.0
        for row in list(store.db.execute("SELECT * FROM jobs WHERE scope=? AND status IN ('pending','failed') ORDER BY pass,id",(scope,))):
            current=store.db.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()
            if not current or current[0] not in {'pending','failed'}:continue
            if failed_only and row['status']!='failed':continue
            if pass_number is not None and row['pass']!=pass_number:continue
            if done>=max_batches or store.setting('run_state') in {'paused','cancelled'}:break
            deps=[]
            for jid in json.loads(row['deps']):
                dep=store.db.execute('SELECT status,result,context,pass FROM jobs WHERE id=?',(jid,)).fetchone()
                if not dep or dep['status']!='done':break
                prior_context=json.loads(dep['context'])
                deps.append({'job':jid,'pass':dep['pass'],'instance_bindings':{a:{k:v for k,v in instance.items() if k in {'node','id','record_id','title','label'}} for a,instance in prior_context['instances'].items()},'result':json.loads(dep['result'])})
            else:
                context=json.loads(row['context']);context['prior_results']=deps;context['require_chinese_notes']=True
                prompt=messages(context,row['pass']);estimate=sum(len(m['content'].encode('utf8')) for m in prompt)
                # Conservative upper bound; server performs actual token/context checks.
                if estimate>max_input_tokens*3:
                    with store.db:store.db.execute("UPDATE jobs SET error='Context exceeds configured safety bound; larger-context review or rechunk required' WHERE id=?",(row['id'],))
                    continue
                key=digest([provider.name,provider.endpoint,provider.model,getattr(provider,'revision',None),PROMPT_VERSION,prompt,max_tokens,max_input_tokens])
                if row['cache_key']==key and row['attempts']>=3:continue
                cache=store.db.execute("SELECT result FROM jobs WHERE cache_key=? AND status='done'",(key,)).fetchone()
                prior_response=None
                if not cache and row['cache_key']==key:
                    oldcall=store.db.execute('SELECT metadata FROM calls WHERE job=? AND error IS NOT NULL ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
                    if oldcall:
                        prior_response=json.loads(oldcall[0]).get('invalid_response')
                        try:validate_response(prior_response,context)
                        except (ValueError,TypeError):prior_response=None
                worst=0 if provider.name=='local' else ((estimate+64*len(prompt))*provider.input_price+max_tokens*provider.output_price)/1e6
                if spent+worst>max_cost and provider.name!='local':break
                if provider.name=='deepseek':
                    cap=store.setting('deepseek_budget_cny')
                    if cap is None:raise ValueError('Persistent paid budget must be explicitly configured')
                    reserved=store.setting('deepseek_committed_upper_cny') or 0.0
                    if reserved+worst>cap:break
                    store.setting('deepseek_committed_upper_cny',reserved+worst)
                with store.db:store.db.execute("UPDATE jobs SET status='running',attempts=?,cache_key=?,error=NULL WHERE id=?",(row['attempts']+1 if row['cache_key']==key else 1,key,row['id']))
                start=time.perf_counter()
                metrics={};raw=None
                try:
                    if cache or prior_response:
                        value=validate_response(json.loads(cache[0]) if cache else prior_response,context)
                        metrics={'input_tokens':0,'output_tokens':0,'seconds':0,'cost':0,'cache_hit':1}
                    else:
                        raw,metrics=provider.run(prompt,max_tokens,constrained_schema(context));value=validate_response(raw,context);metrics['cache_hit']=0
                    if provider.name=='deepseek':store.setting('deepseek_committed_upper_cny',(store.setting('deepseek_committed_upper_cny') or 0)-worst+metrics['cost'])
                    spent+=metrics['cost'];done+=1
                    with store.db:
                        if not store.db.in_transaction:store.db.execute('BEGIN IMMEDIATE')
                        if store.db.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]=='cancelled':
                            store.db.execute('INSERT INTO calls(job,provider,model,input_tokens,output_tokens,seconds,cost,cache_hit,error,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (row['id'],provider.name,provider.model,metrics['input_tokens'],metrics['output_tokens'],metrics['seconds'],metrics['cost'],metrics['cache_hit'],None,canonical({**metrics,'discarded_after_research_undo':True})))
                            continue
                        store.db.execute("UPDATE jobs SET status='done',result=? WHERE id=?",(canonical(value),row['id']))
                        from .related import stage
                        staged=stage(store,row,context,value,provider)
                        if not staged:
                            for n,p in enumerate(value['proposals']):
                                pid=digest([row['id'],n,p]);payload={'proposal_version':1,'context_hash':digest(context),'context':context,'suggestion':p,'status':'pending','origin':'LLM','game_verified':False}
                                store.db.execute('INSERT OR IGNORE INTO proposals(id,job,payload) VALUES(?,?,?)',(pid,row['id'],canonical(payload)))
                            if context.get('supersedes_job'):
                                store.db.execute("UPDATE proposals SET status='superseded' WHERE job=? AND status='pending'",(context['supersedes_job'],))
                        store.db.execute('INSERT INTO calls(job,provider,model,input_tokens,output_tokens,seconds,cost,cache_hit,error,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (row['id'],provider.name,provider.model,metrics['input_tokens'],metrics['output_tokens'],metrics['seconds'],metrics['cost'],metrics['cache_hit'],None,canonical({**metrics,'validated_response':value,'prompt_version':PROMPT_VERSION,'model_revision':getattr(provider,'revision',None)})))
                except Exception as e:
                    done+=1
                    from .providers import ProviderPreflightError
                    preflight=isinstance(e,ProviderPreflightError)
                    if preflight and provider.name=='deepseek':store.setting('deepseek_committed_upper_cny',(store.setting('deepseek_committed_upper_cny') or 0)-worst)
                    with store.db:
                        store.db.execute("UPDATE jobs SET status='failed',error=? WHERE id=? AND status!='cancelled'",(type(e).__name__+': '+str(e)[:300],row['id']))
                        store.db.execute('INSERT INTO calls(job,provider,model,input_tokens,output_tokens,seconds,cost,cache_hit,error,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (row['id'],provider.name,provider.model,metrics.get('input_tokens'),metrics.get('output_tokens'),time.perf_counter()-start,metrics.get('cost'),0,type(e).__name__,
                             canonical({'billable_usage_unknown':provider.name!='local' and not metrics and not preflight,'provider_metrics':metrics,'invalid_response':raw,'no_request_sent':preflight})))
                    # A paid failure may have been billable; never retry without
                    # a fresh explicit budget and provider usage reconciliation.
                    if provider.name!='local':break
                continue
        if store.setting('run_state') not in {'paused','cancelled'}:store.setting('run_state','budget_finished' if done>=max_batches else 'idle')
        return store.report()
