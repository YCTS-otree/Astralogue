"""Chapter boundaries from mission configuration; transcript policy is external evidence."""
from pathlib import Path
from collections import defaultdict,Counter
from copy import deepcopy
from astralogue.model import Bundle,Node,Edge,Mission,Diagnostic,load_json,file_hash,digest
from astralogue.hsr.manifest import create_manifest
from astralogue.adapters.hf import verify
from astralogue import __version__


def inventory(source,root):
    manifest=create_manifest(source);hf=verify(root);by_title=defaultdict(list)
    for name in hf['files']:
        if name.startswith('missions/'):
            raw=load_json(root/name);by_title[raw['title']].append((name,hf['files'][name]['sha256']))
    records={m['id']:m for m in manifest['missions']};chapters=defaultdict(list)
    for m in records.values():
        if m['category']=='TRAILBLAZE':chapters[str(m['chapter'])].append(m)
    result=[]
    for cid,group in chapters.items():
        plans=[]
        for start in group:
            auto=any(p.get('Type')=='Auto' for p in start['prerequisites'])
            external=any(p.get('Type')=='MultiSequence' and str(p.get('Value')) in records and str(records[str(p['Value'])]['chapter'])!=cid for p in start['prerequisites'])
            if not (auto or external) or not start['named_story_candidate']:continue
            chain=[];seen=set();current=start;exit_=None;failure=None
            while current and current['id'] not in seen:
                seen.add(current['id']);chain.append(current)
                target=records.get(str(current['next_track']))
                if target and str(target['chapter'])!=cid:exit_={'from':current['id'],'to':target['id'],'next_chapter':target['chapter'],'evidence':'MainMission.NextTrackMainMission'};break
                if not target:failure='missing_declared_successor';break
                current=target
            if not exit_ and not failure:failure='cycle'
            tasks=[]
            for m in chain:
                if tasks and tasks[-1]['title']==m['title']:tasks[-1]['main_ids'].append(m['id']);continue
                candidates=by_title.get(m['title'],[]);unique={sha:name for name,sha in candidates}
                tasks.append({'title':m['title'],'main_ids':[m['id']],'hf':next(iter(unique.values())) if len(unique)==1 else None,'hf_candidates':[n for n,_ in candidates]})
            missing=[t['title'] for t in tasks if not t['hf']]
            plans.append({'id':'chapter:'+cid+':'+start['id'],'chapter_id':cid,'title':start['chapter_title'],'entry':{'main':start['id'],'condition':start['prerequisites'],'auto':auto},'exit':exit_,'tasks':tasks,'internal_records':chain,'excluded_records':[m for m in group if m['id'] not in seen],'missing_transcripts':missing,'failure':failure,'feasible':bool(exit_ and not missing and not failure)})
        result.append({'chapter':cid,'title':group[0]['chapter_title'],'plans':plans,'records':len(group)})
    return {'schema':1,'source':manifest['source'],'hf_revision':hf['revision'],'chapters':result,'inputs':{p:file_hash(source/p) for p in ['ExcelOutput/MainMission.json','ExcelOutput/MissionChapterConfig.json']}}


def select(inv):
    plans=[p for c in inv['chapters'] for p in c['plans'] if p['feasible'] and p['entry']['auto']]
    if len(plans)!=1:raise ValueError('Initial complete chapter is not uniquely identified; select explicit plan')
    return plans[0]


def native_paths(pack,evidence,mid,limit=64):
    from astralogue.runtime import Runtime,DialogueEvent,ChoiceEvent,EndEvent,BlockedEvent,DiagnosticEvent
    queue=[(Runtime(pack,mid),[])];paths=[];steps=0
    while queue:
        rt,trace=queue.pop()
        for _ in range(150):
            steps+=1
            if steps>4000 or len(paths)+len(queue)>limit:return None
            e=rt.next()
            if isinstance(e,DialogueEvent):
                sid=pack.node(e.node).data.get('sentence_id')
                if not sid:return None
                trace=trace+[sid]
            elif isinstance(e,ChoiceEvent):
                for o in e.options:
                    sid=evidence.option_ids.get((e.node,o.value))
                    if sid is None:return None
                    child=Runtime(pack,mid);child.state=deepcopy(rt.state);child.choose(o.value);queue.append((child,trace+[sid]))
                break
            elif isinstance(e,EndEvent):paths.append(trace);break
            elif isinstance(e,BlockedEvent):return None
        else:return None
    return paths


def compile_arc(plan,source,root,aligned_dir,control_pack,variant_review=None):
    from astralogue.hsr.hf_alignment import GameEvidence
    from astralogue.runtime import Runtime,DialogueEvent,ChoiceEvent,EndEvent,BlockedEvent,DiagnosticEvent
    from astralogue.narrative import Reconstruction
    evidence=GameEvidence(control_pack,source);base=control_pack.bundle();arc='arc:'+plan['id']
    r=Reconstruction(base,arc,plan['title']+' · 完整转录路径',arc+':consent');b=r.bundle;info=r.info
    b.metadata['version']=__version__;info['entries']={'reader':arc}
    info['modes'][arc].update(scope='story_arc',arc=plan['id'])
    meta={'plan':plan,'source_policy':'source-transcript-v1','hf':verify(root),'rows':[],'task_boundaries':[],'injections':[],'gaps':[]}
    b.metadata['story_arcs']={arc:meta}
    catalog={x['TalkSentenceID']:x for x in load_json(source/'ExcelOutput/TalkSentenceConfig.json') if 'TalkSentenceID' in x};chs=load_json(source/'TextMap/TextMapCHS.json')
    def edge(a,z,cls='HF_TRANSCRIPT_ORDER',proof=None,**kw):
        eid=r.edge(a,z,'inferred',{'class':cls,'proof':proof},'source-transcript-v1',**kw)
        return eid
    end=arc+':end';r.node(end,'end',completion_scope='story_arc_reader',native_completion=False)
    following=end
    reviews=variant_review or {'records':[]}
    meta['variant_review']=reviews
    # Build backwards solely to materialize explicit forward edges, not to infer order.
    for task_no in range(len(plan['tasks'])-1,-1,-1):
        task=plan['tasks'][task_no];name=task['hf'];raw=load_json(root/name);a=load_json(aligned_dir/(Path(name).stem+'.json'))
        if a['inputs']['hf']!=file_hash(root/name):raise ValueError('HF alignment stale')
        variants={v['index']:v for v in reviews['records'] if v['file']==name}
        for conflict in a['relations']:
            if conflict['status']=='POTENTIAL_CONTROL_CONFLICT':
                v=variants.get(conflict['target_index'])
                if not v or v['replacement'] not in conflict['other_known_targets'] or reviews.get('hf_sha256')!=a['inputs']['hf'] or reviews.get('control_pack_id')!=a['control_pack_id']:raise ValueError('Unreviewed control conflict blocks chapter')
        rows=raw['story'];stem=arc+':task:'+str(task_no)
        out=stem+':exit';r.node(out,'dialogue',arc_action='task_exit',task=task_no)
        b.nodes[-1].text=b.text(out+':text','【转录范围读毕】'+task['title']);b.nodes[-1].speaker=b.text('arc:system','阅读进度')
        edge(out,following,'MISSION_TRANSITION',{'main_ids':task['main_ids'],'next_task':plan['tasks'][task_no+1]['main_ids'] if task_no+1<len(plan['tasks']) else plan['exit']})
        following=out
        selected=[a['bindings'].get('tree/'+str(i),{}).get('selected') for i in range(len(rows))]
        injections={}
        # A complete, already executable performance may replace its EXACT recorded span.
        for mid,label in evidence.labels.items():
            if label.get('scope')!='PERFORMANCE_FRAGMENT' or label.get('parent') not in {'hsr:mission:'+x for x in a['game_evidence']['main_candidates']}:continue
            paths=native_paths(control_pack,evidence,mid)
            if not paths or len(paths)<2:continue
            for path in paths:
                for start in range(len(rows)-len(path)+1):
                    if selected[start:start+len(path)]==path and all(x['type'] in {'對話','对话'} for x in rows[start:start+len(path)]):
                        injections[start+len(path)-1]=(start,mid,paths,path)
        i=len(rows)-1
        while i>=0:
            if i in injections:
                start,mid,paths,recorded=injections[i];memo={};active=set()
                def project(rt):
                    key=digest({k:v for k,v in rt.snapshot().items() if k!='choices'})
                    if key in active:raise ValueError('Native projection loop')
                    if key in memo:return memo[key]
                    active.add(key);e=rt.next()
                    while isinstance(e,DiagnosticEvent):e=rt.next()
                    nid=stem+':native:'+str(start)+':'+key[:20];memo[key]=nid
                    if isinstance(e,EndEvent):memo[key]=following;active.remove(key);return following
                    if isinstance(e,DialogueEvent):
                        n=control_pack.node(e.node);sid=n.data['sentence_id'];b.nodes.append(Node(nid,arc,'dialogue',n.text,n.speaker,{'sentence_id':sid,'content_origin':'GAME','native_node':n.id,'task':task_no,'native_span':[start,i]}))
                        target=project(rt);edge(nid,target,'GAME_VERIFIED_LOCAL',{'native_node':n.id,'entry':mid})
                    elif isinstance(e,ChoiceEvent):
                        r.node(nid,'choice',reader_action='native_choice',task=task_no,native_node=e.node,native_span=[start,i],source_option_ids={o.value:evidence.option_ids[(e.node,o.value)] for o in e.options},recorded_value=next(o.value for o in e.options if evidence.option_ids[(e.node,o.value)] in recorded))
                        for option in e.options:
                            child=Runtime(control_pack,mid);child.state=deepcopy(rt.state);child.choose(option.value)
                            edge(nid,project(child),'GAME_VERIFIED_LOCAL',{'entry':mid,'native_choice':e.node},kind='option',text=next(x.text for x in control_pack.edges(e.node) if x.value==option.value),value=option.value)
                    else:raise ValueError('Native injection blocked')
                    active.remove(key);return nid
                following=project(Runtime(control_pack,mid));meta['injections'].append({'file':name,'start':start,'end':i,'entry':mid,'compiled_entry':following,'paths':paths,'recorded':recorded})
                for j in range(start,i+1):meta['rows'].append({'file':name,'index':j,'source':'GAME','id':selected[j],'native_span':[start,i]})
                i=start-1;continue
            item=rows[i];nid=stem+':row:'+str(i);kind=item.get('type');binding=a['bindings'].get('tree/'+str(i),{});sid=binding.get('selected');game=kind in {'對話','对话'} and sid in catalog
            if kind not in {'對話','对话','旁白','動畫','动画'} or not isinstance(item.get('content'),str) or not item['content']:
                r.node(nid,'unknown',operation='MissingOrUnknownTranscriptItem',raw=item);meta['gaps'].append({'file':name,'index':i,'blocking':True});following=nid;i-=1;continue
            comparison=next((v for v in variants.values() if i in v['notes']),None)
            if comparison:game=False
            if game:
                row=catalog[sid];text=chs[str(row['TalkSentenceText']['Hash'])];namehash=str(row.get('TextmapTalkSentenceName',{}).get('Hash'));speaker=chs.get(namehash,item.get('speaker') or '未标注角色');origin='GAME'
            else:text=item['content'];speaker=('旁白' if kind=='旁白' else '舞台说明' if kind in {'動畫','动画'} else item.get('speaker') or '未标注角色');origin='COMMUNITY_TRANSCRIPT'
            if comparison:speaker='版本/上下文对照附注（不作当前剧情事件）';text=item['content']
            # Unknown explicit condition templates must stop, not silently pick a branch.
            if any(mark in text for mark in ['【分支条件','[IF ','（若选择','如果选择选项']):
                r.node(nid,'unknown',operation='UnresolvedSourceCondition',raw=item);meta['gaps'].append({'file':name,'index':i,'blocking':True});following=nid;i-=1;continue
            key=b.text(nid+':text',text);speaker_key=b.text(nid+':speaker',('社区转录·' if origin=='COMMUNITY_TRANSCRIPT' else '')+speaker)
            if kind in {'對話','对话'} and (sid in evidence.option_groups or item.get('speaker') in {'開拓者','开拓者'}):
                r.node(nid,'choice',reader_action='recorded_path',reader_message='来源 '+origin+'；转录只记录此发言/选项，按记录路径继续，不代表全部游戏选项。',task=task_no,hf_index=i,content_origin=origin)
                edge(nid,following,kind='option',text=key,value='recorded')
            else:b.nodes.append(Node(nid,arc,'dialogue',key,speaker_key,{'task':task_no,'hf_index':i,'content_origin':origin,'sentence_id':sid if game else None,'content_kind':kind}));edge(nid,following,proof={'file':task['hf'],'index':i,'sha256':a['inputs']['hf'],'url':raw['url']})
            b.source_refs.append({'node':nid,'file':task['hf'],'pointer':'/story/'+str(i),'sha256':a['inputs']['hf'],'raw':item,'source_url':raw['url']})
            meta['rows'].append({'file':task['hf'],'index':i,'source':origin,'id':sid if game else None,'kind':kind,'node':nid})
            following=nid
            if i in variants:
                v=variants[i];replacement=v['replacement'];row=catalog[replacement];gid=nid+':current-game-version'
                b.nodes.append(Node(gid,arc,'dialogue',b.text(gid+':text',chs[str(row['TalkSentenceText']['Hash'])]),b.text(gid+':speaker',chs.get(str(row.get('TextmapTalkSentenceName',{}).get('Hash')),'未标注角色')),{'task':task_no,'sentence_id':replacement,'content_origin':'GAME_SUPPLEMENT','variant_review':v}))
                edge(gid,nid,'VERSION_COMPARISON_NOTE',v);following=gid
            i-=1
        entry=stem+':entry';r.node(entry,'dialogue',arc_action='task_enter',task=task_no)
        b.nodes[-1].text=b.text(entry+':text','【进入任务】'+task['title']);b.nodes[-1].speaker='arc:system';edge(entry,following,'MISSION_TRANSITION',{'main_ids':task['main_ids']});following=entry
        meta['task_boundaries'].append({'task':task_no,'title':task['title'],'entry':entry,'exit':out,'file':task['hf'],'entries':len(rows)})
    r.confirm(arc+':consent',following,'接受固定版本社区转录的阅读顺序：未匹配内容将标作社区转录，旁白/舞台说明保留；缺少的分支不伪装完整游戏执行',action='source_transcript_policy')
    meta['rows'].sort(key=lambda x:(next(i for i,t in enumerate(plan['tasks']) if t['hf']==x['file']),x['index']))
    meta['task_boundaries'].sort(key=lambda x:x['task'])
    meta['summary']={'tasks':len(plan['tasks']),'internal_records':len(plan['internal_records']),'source_items':len(meta['rows']),'origins':dict(Counter(x['source'] for x in meta['rows'])),'blocking_gaps':len(meta['gaps']),'native_strict_complete':False,'branch_coverage':'source-recorded path plus fully projected known local branches; remaining branches unprovided'}
    return b
