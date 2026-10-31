"""Independent original-control evidence and CHS dataset alignment."""
from collections import deque,defaultdict,Counter
from copy import deepcopy
from pathlib import Path
from astralogue.model import load_json,file_hash,digest,canonical
from astralogue.storypack import StoryPack
from astralogue.runtime import Runtime,DialogueEvent,ChoiceEvent,EndEvent,BlockedEvent
from astralogue.adapters.wiki import parse,normalize
from astralogue.adapters.wiki.index import DialogueIndex
from astralogue.adapters.hf import verify

ALIGNER_VERSION='hf-chs-v5'

class GameEvidence:
    def __init__(self,pack,source):
        self.pack=pack;self.bundle=pack.bundle();self.labels=self.bundle.metadata.get('mission_labels',{})
        self.manifest=self.bundle.metadata['mission_manifest'];self.source=source
        if self.manifest['source'].get('revision')!=load_json(source/'source.json').get('revision'):raise ValueError('Game control pack/source revision mismatch')
        for relative in ['TextMap/TextMapCHS.json','ExcelOutput/TalkSentenceConfig.json']:
            expected=self.bundle.metadata.get('inputs',{}).get('source0:'+relative)
            if expected and file_hash(source/relative)!=expected:raise ValueError('Control text source hash mismatch')
        self.refs={r['node']:r for r in self.bundle.source_refs if r.get('node')}
        self.option_ids={};self.option_groups={}
        for n in self.bundle.nodes:
            if n.kind!='choice':continue
            ref=self.refs.get(n.id,{});file=ref.get('file');ptr=ref.get('pointer');raw=None
            if isinstance(file,str) and file.startswith(('Config/','Story/')) and file.endswith('.json') and ptr is not None:
                path=(source/file).resolve()
                if not path.is_relative_to(source.resolve()):raise ValueError('Source reference outside input')
                if path.is_file():
                    expected=self.bundle.metadata.get('inputs',{}).get('source0:'+file)
                    if expected and file_hash(path)!=expected:raise ValueError('Control source hash mismatch: '+file)
                    raw=load_json(path)
                    try:
                        for part in ptr.strip('/').split('/'):
                            if part:raw=raw[int(part)] if isinstance(raw,list) else raw[part.replace('~1','/').replace('~0','~')]
                    except (KeyError,IndexError,ValueError,TypeError):raw=None
            if not isinstance(raw,dict) or not isinstance(raw.get('OptionList'),list):continue
            options=raw['OptionList']
            for edge in pack.edges(n.id):
                try:option=options[int(edge.value)-1]
                except (ValueError,TypeError,IndexError):continue
                sid=option.get('TalkSentenceID')
                if sid is not None:
                    self.option_ids[(n.id,edge.value)]=sid
                    self.option_groups[sid]={'node':n.id,'ids':[o.get('TalkSentenceID') for o in options],'source':ref}
    def static_pairs(self,entries):
        """Explicit local IR adjacency, even if its fragment cannot be entered.

        Stops at unknown operations, calls and conditions; never skips a choice.
        """
        nodes={n.id:n for n in self.bundle.nodes};results=[]
        def frontier(nid,signal=None):
            seen=set()
            for _ in range(100):
                if nid in seen:return []
                seen.add(nid);n=nodes[nid]
                if n.mission not in entries:return []
                if n.kind=='dialogue' and n.data.get('sentence_id'):
                    return [(n.data['sentence_id'],n.id)]
                if n.kind=='choice':
                    return [(self.option_ids[(n.id,e.value)],n.id) for e in self.pack.edges(n.id) if (n.id,e.value) in self.option_ids]
                if n.kind=='wait':
                    if signal!=n.data.get('event'):return []
                    signal=None
                elif n.kind=='emit':signal=n.data.get('event')
                elif n.kind!='noop':return []
                edges=self.pack.edges(n.id)
                if len(edges)!=1 or edges[0].kind!='next' or edges[0].condition is not None:return []
                nid=edges[0].target
            return []
        for n in self.bundle.nodes:
            if n.mission not in entries:continue
            starts=[]
            if n.kind=='dialogue' and n.data.get('sentence_id'):
                starts=[(n.data['sentence_id'],e.target,None) for e in self.pack.edges(n.id) if e.kind=='next' and e.condition is None]
            elif n.kind=='choice':
                starts=[(self.option_ids[(n.id,e.value)],e.target,n.data.get('option_events',{}).get(e.value)) for e in self.pack.edges(n.id) if (n.id,e.value) in self.option_ids and e.condition is None]
            for sid,target,signal in starts:
                for following,tid in frontier(target,signal):
                    results.append({'source':sid,'target':following,'evidence':[{'entry':n.mission,'source_node':n.id,'node':tid,'source_ref':self.refs.get(tid),'source_ref_from':self.refs.get(n.id),'validation':'static_original_ir','pack_id':self.pack.metadata['pack_id']}]})
        return results

    def collect(self,title,max_states=3000,max_steps=30000):
        mains=[m['id'] for m in self.manifest['missions'] if normalize(m.get('title') or '')==normalize(title) and m['category']=='TRAILBLAZE']
        parents={'hsr:mission:'+m for m in mains}
        entries=[m.id for m in self.bundle.missions if m.id in parents or self.labels.get(m.id,{}).get('parent') in parents]
        owned=set();pairs=defaultdict(list);paths=[];blocked=[];steps=0;states=0;truncated=False;runtime_reached=set()
        for n in self.bundle.nodes:
            if n.mission in entries:
                sid=n.data.get('sentence_id',n.data.get('talk_sentence_id'))
                if sid:owned.add(sid)
                for (nid,_),oid in self.option_ids.items():
                    if nid==n.id:owned.add(oid)
        for mid in entries:
            queue=deque([(Runtime(self.pack,mid),None,[])])
            seen=set()
            while queue:
                rt,last,trace=queue.popleft()
                for _ in range(500):
                    state=rt.snapshot();state.pop('choices')
                    marker=canonical([state,last])
                    if marker in seen:break
                    if states>=max_states or steps>=max_steps:truncated=True;break
                    seen.add(marker);states+=1;steps+=1;e=rt.next()
                    if isinstance(e,DialogueEvent):
                        n=self.pack.node(e.node);sid=n.data.get('sentence_id',n.data.get('talk_sentence_id'))
                        if sid:
                            runtime_reached.add(sid)
                            if last:pairs[(last,sid)].append({'entry':mid,'node':e.node,'source_ref':self.refs.get(e.node),'pack_id':self.pack.metadata['pack_id'],'state_variables':deepcopy(rt.state.variables)})
                            last=sid;trace=trace+[sid]
                    elif isinstance(e,ChoiceEvent):
                        for option in e.options:
                            child=Runtime(self.pack,mid);child.state=deepcopy(rt.state);child.choose(option.value)
                            sid=self.option_ids.get((e.node,option.value));childtrace=trace
                            if sid:
                                runtime_reached.add(sid)
                                if last:pairs[(last,sid)].append({'entry':mid,'choice_node':e.node,'value':option.value,'pack_id':self.pack.metadata['pack_id'],'source_ref':self.refs.get(e.node)})
                                childtrace=trace+[sid]
                            queue.append((child,sid,childtrace))
                        break
                    elif isinstance(e,EndEvent):paths.append({'entry':mid,'ids':trace});break
                    elif isinstance(e,BlockedEvent):blocked.append({'entry':mid,'node':e.node,'code':e.code});break
                else:truncated=True
                if truncated:break
            if truncated:break
        runtime_pairs=set(pairs)
        for pair in self.static_pairs(entries):pairs[(pair['source'],pair['target'])].extend(pair['evidence'])
        return {'runtime_reached_ids':sorted(runtime_reached),'runtime_pair_ids':[list(p) for p in sorted(runtime_pairs)],'main_candidates':mains,'owned_ids':sorted(owned),'pairs':[{'source':a,'target':b,'evidence':ev} for (a,b),ev in sorted(pairs.items())], 'paths':paths,'blocked':blocked,'steps':steps,'states':states,'truncated':truncated,'option_groups':self.option_groups}


def convert(root,name):
    manifest=verify(root,[name]);raw=load_json(root/name)
    if not isinstance(raw.get('story'),list):raise ValueError('HF story must be an array')
    tree=[]
    for i,item in enumerate(raw['story']):
        typ=item.get('type');kind={'對話':'dialogue','对话':'dialogue','旁白':'narration','動畫':'animation','动画':'animation'}.get(typ,'unknown')
        tree.append({'type':kind,'text':item.get('content',''),'speaker':item.get('speaker'),'position':i,'raw_type':typ,'raw':item})
    snapshot={'format':'wiki-tree-v1','title':raw['title'],'url':raw.get('url'),'page_id':None,'revision_id':manifest['revision'],'license':manifest['license_metadata'],'tree':tree,'dataset':{'repository':manifest['repository'],'revision':manifest['revision'],'file':name,'sha256':manifest['files'][name]['sha256'],'author':manifest['author'],'limitations':manifest['scope']},'raw_json':raw}
    return parse(snapshot)


def align_dataset(root,name,source,index,evidence):
    parsed=convert(root,name);game=evidence.collect(parsed['provenance']['title']);owned=set(game['owned_ids']);bindings={}
    for i,n in enumerate(parsed['tree']):
        if n['type']=='dialogue':bindings['tree/'+str(i)]=index.match(n['text'],n.get('speaker'),owned)
    pair_index={(p['source'],p['target']):p for p in game['pairs']};adjacency=defaultdict(set)
    for pos,binding in bindings.items():
        if binding['selected'] is not None or not binding['fuzzy_candidates']:continue
        i=int(pos.split('/')[-1]);left=bindings.get('tree/'+str(i-1),{}).get('selected');right=bindings.get('tree/'+str(i+1),{}).get('selected')
        confirmed=[]
        for candidate in binding['fuzzy_candidates']:
            a=pair_index.get((left,candidate['id']));z=pair_index.get((candidate['id'],right))
            if a and z and {e.get('node') for e in a['evidence'] if e.get('validation')=='static_original_ir'} & {e.get('source_node') for e in z['evidence'] if e.get('validation')=='static_original_ir'}:confirmed.append((candidate,a,z))
        if len(confirmed)==1:
            candidate,a,z=confirmed[0];binding.update(selected=candidate['id'],basis='game_two_sided_context',independent_evidence={'left':a,'right':z})

    for a,b in pair_index:adjacency[a].add(b)
    relations=[];segments=[];current=[];previous=None
    for i,n in enumerate(parsed['tree']):
        binding=bindings.get('tree/'+str(i));sid=binding['selected'] if binding else None
        if sid is None:
            if len(current)>=2:segments.append(current)
            current=[];previous=None;continue
        relation=None
        if previous is not None:
            a=bindings['tree/'+str(previous)]['selected'];pair=(a,sid)
            status=('GAME_CROSS_CONFIRMED' if list(pair) in game.get('runtime_pair_ids',[]) else 'GAME_STATIC_CROSS_CONFIRMED') if pair in pair_index else 'POTENTIAL_CONTROL_CONFLICT' if a in adjacency else 'HF_ORDER_ONLY'
            relation={'source_index':previous,'target_index':i,'source_id':a,'target_id':sid,'status':status,'evidence':pair_index.get(pair),'other_known_targets':sorted(adjacency[a])}
            relations.append(relation)
            if status=='POTENTIAL_CONTROL_CONFLICT':
                if len(current)>=2:segments.append(current)
                current=[]
        current.append(i);previous=i
    if len(current)>=2:segments.append(current)
    counts=Counter(n['type'] for n in parsed['tree']);allbindings=list(bindings.values())
    known_options={int(k):v for k,v in game['option_groups'].items()};selected={b['selected'] for b in allbindings if b['selected'] is not None}
    option_sets={tuple(v['ids']) for k,v in known_options.items() if k in selected}
    report={'title':parsed['provenance']['title'],'file':name,'dataset_revision':parsed['snapshot']['dataset']['revision'],'game_revision':load_json(source/'source.json')['revision'],'version_note':'Dataset through 3.0; local game snapshot 4.6.0; no version equivalence assumed','total_entries':len(parsed['tree']),'dialogue_entries':counts['dialogue'],'non_dialogue_entries':len(parsed['tree'])-counts['dialogue'],
        'unique_raw_exact':sum(b['exact_count']==1 and b['candidates'][0]['method']=='exact' for b in allbindings),'unique_normalized_exact':sum(b['exact_count']==1 and b['candidates'][0]['method']=='normalized_exact' for b in allbindings),'multiple_exact':sum(b['exact_count']>1 for b in allbindings),'fuzzy_candidate_entries':sum(bool(b['fuzzy_candidates']) for b in allbindings),'independently_confirmed_fuzzy':sum(b.get('basis')=='game_two_sided_context' for b in allbindings),'completely_unmatched':sum(not b['candidates'] and not b['fuzzy_candidates'] for b in allbindings),'selected_ids':sum(b['selected'] is not None for b in allbindings),'selected_distinct_ids':len(selected),
        'cross_confirmed_relations':sum(x['status'] in {'GAME_CROSS_CONFIRMED','GAME_STATIC_CROSS_CONFIRMED'} for x in relations),'potential_control_conflicts':sum(x['status']=='POTENTIAL_CONTROL_CONFLICT' for x in relations),'proven_control_conflicts':0,'hf_only_relations':sum(x['status']=='HF_ORDER_ONLY' for x in relations),'missing_known_options':sum(len(set(ids)-selected) for ids in option_sets),'continuous_segments':len(segments),'segment_lengths':[len(x) for x in segments],'full_game_tasks_proven':0,'new_game_verified_relations':0,'runtime':'not_executed'}
    return {'hf_alignment_version':1,'control_pack_id':evidence.pack.metadata['pack_id'],'parsed':parsed,'bindings':bindings,'game_evidence':game,'relations':relations,'segments':segments,'report':report,'source':load_json(source/'source.json'),'inputs':{'chs':file_hash(source/'TextMap/TextMapCHS.json'),'sentences':file_hash(source/'ExcelOutput/TalkSentenceConfig.json'),'hf':parsed['snapshot']['dataset']['sha256']}}


def previous_reader_pairs(pack_paths,max_events=2000):
    """Dedup baseline Reader adjacencies; these are not game-control proofs."""
    pairs=set()
    for path in pack_paths:
        with StoryPack(path) as pack:
            entries=pack.metadata.get('narrative',{}).get('entries',{})
            if not entries.get('reader'):continue
            queue=deque([(Runtime(pack,entries['reader']),None)]);steps=0
            while queue and steps<max_events:
                rt,last=queue.popleft()
                while steps<max_events:
                    steps+=1;e=rt.next()
                    if isinstance(e,DialogueEvent):
                        n=pack.node(e.node);sid=n.data.get('talk_sentence_id',n.data.get('sentence_id'))
                        if last is not None and sid is not None:pairs.add((last,sid))
                        last=sid
                    elif isinstance(e,ChoiceEvent):
                        action=pack.node(e.node).data.get('reader_action')
                        for opt in e.options:
                            child=Runtime(pack,rt.state.mission);child.state=deepcopy(rt.state);child.choose(opt.value)
                            option_sid=int(opt.value) if not action and opt.value.isdecimal() and int(opt.value)>100000 else None
                            if option_sid and last:pairs.add((last,option_sid))
                            queue.append((child,option_sid or last))
                        break
                    elif isinstance(e,(EndEvent,BlockedEvent)):break
    return pairs


def compile_dataset_reader(alignment,source,base,previous_pairs=frozenset()):
    """Reuse M8 graph compiler, adding explicit dataset-only transition gates."""
    from astralogue.adapters.wiki import build as build_wiki
    from astralogue.model import Node,Edge
    from astralogue import __version__
    if alignment.get('control_pack_id')!=base.metadata.get('pack_id'):raise ValueError('Alignment/control pack identity mismatch')
    for key,relative in [('chs','TextMap/TextMapCHS.json'),('sentences','ExcelOutput/TalkSentenceConfig.json')]:
        if alignment['inputs'][key]!=file_hash(source/relative):raise ValueError('Stale game input hash')
    original=deepcopy(base.to_dict());bundle=base
    game_options={int(k):v for k,v in alignment['game_evidence']['option_groups'].items()}
    relations={(r['source_index'],r['target_index']):r for r in alignment['relations']}
    missions=[];pair_inventory=set()
    for indices in alignment['segments']:
        nodes=[];bindings={}
        for slot,i in enumerate(indices):
            n=deepcopy(alignment['parsed']['tree'][i]);binding=alignment['bindings']['tree/'+str(i)];sid=binding['selected']
            shared={'selected':sid,'status':'WIKI_ALIGNED','candidates':binding['candidates'],'hf_index':i,'basis':binding['basis']}
            if sid in game_options:
                nodes.append({'type':'choice','options':[{'text':n['text'],'body':[]}]});bindings[f'tree/{slot}/options/0']=shared
            else:nodes.append(n);bindings[f'tree/{slot}']=shared
        parsed={'tree':nodes,'provenance':{**alignment['parsed']['provenance'],'title':alignment['report']['title']+f' · HF 条目 {indices[0]}–{indices[-1]}（节选）'},'snapshot':alignment['parsed']['snapshot']}
        normalized={'parsed':parsed,'bindings':bindings,'inputs':alignment['inputs'],'source':alignment['source'],'review':None}
        ns='hf:'+alignment['inputs']['hf'][:16]+f':{indices[0]}-{indices[-1]}'
        bundle=build_wiki(normalized,source,strict=bundle,namespace=ns);info=bundle.metadata['narrative'];mid=ns+':reader';missions.append(mid)
        consent=next(n for n in bundle.nodes if n.id==ns+':consent')
        consent.data.update(reader_action='hf_consent',reader_message='HF 第一选项转录节选：未覆盖全部选项与原生任务；未知顺序需逐条确认。')
        consent_edge=next(e for e in bundle.edges if e.source==consent.id)
        bundle.texts[consent_edge.text]['CHS']=consent.data['reader_message']+'确认进入此明确范围。'
        info['policies'][consent.id].update(action='hf_consent',message=consent.data['reader_message'])
        info['modes'][mid].update(scope='hf_contiguous_excerpt',hf_indices=indices,dataset_first_option_only=True)
        info.setdefault('wiki_alignments',{})[mid]=normalized
        info.setdefault('hf_alignment',{})[alignment['report']['file']]=alignment
        info['entries']['reader']=mid
        known_nodes={n.id:n for n in bundle.nodes}
        for slot,i in enumerate(indices):
            nid=ns+':tree/'+str(slot);node=known_nodes[nid];binding=alignment['bindings']['tree/'+str(i)]
            node.data.update(hf_index=i,talk_sentence_id=binding['selected'],hf_file=alignment['report']['file'])
            bundle.source_refs.append({'node':nid,'file':alignment['report']['file'],'pointer':'/story/'+str(i),'sha256':alignment['inputs']['hf'],'original_id':binding['selected'],'raw':alignment['parsed']['tree'][i]['raw'],'origin':'HF_DATASET'})
            if node.kind=='choice':
                node.data.update(reader_action='hf_option_excerpt',reader_message='HF 仅保留转录选项；这不是完整原生选项集。原始分支仍保存在原任务入口。')
            if slot+1>=len(indices):continue
            relation=relations[(i,indices[slot+1])];pair=(relation['source_id'],relation['target_id']);pair_inventory.add(pair)
            outgoing=next(e for e in bundle.edges if e.source==nid)
            info['relations'][outgoing.id].update(dataset_status=relation['status'],hf_relation=relation,previously_available=pair in previous_pairs)
            if relation['status'] in {'GAME_CROSS_CONFIRMED','GAME_STATIC_CROSS_CONFIRMED'}:continue
            if relation['status']!='HF_ORDER_ONLY':raise ValueError('Conflicting transition cannot be compiled')
            # Source data provides order, but no reliable complete branch context.
            target=outgoing.target;gate=nid+':confirm_hf_order';outgoing.target=gate
            prompt='HF 转录顺序；缺少完整选项/可选交互上下文，确认采用此文字阅读关系（非游戏原始控制）'
            bundle.nodes.append(Node(gate,mid,'choice',data={'reader_action':'hf_order_confirmation','reader_message':prompt,'hf_relation':relation}))
            text=bundle.text(gate+':label',prompt)
            eid=gate+':next';bundle.edges.append(Edge(eid,gate,target,'option',text,value='confirm'))
            info['relations'][eid]={'origin':'inferred','verified':False,'policy':'hf_order_confirmation','evidence':relation}
            info['policies'][gate]={'action':'hf_order_confirmation','official':False,'evidence':relation}
        info['policies'][ns+':consent']['dataset_warning']='first-option transcript, not complete branch truth'
    if not missions:raise ValueError('No conservative contiguous matched segments')
    # Prefer the longest available excerpt as CLI default; this is menu policy.
    best=max(range(len(alignment['segments'])),key=lambda i:(sum(relations.get((a,b),{}).get('status') in {'GAME_CROSS_CONFIRMED','GAME_STATIC_CROSS_CONFIRMED'} for a,b in zip(alignment['segments'][i],alignment['segments'][i][1:])),len(alignment['segments'][i])))
    bundle.metadata['narrative']['entries']['reader']=missions[best]
    bundle.metadata['version']=__version__
    bundle.metadata['narrative'].update(game='HSR',game_version=alignment['source'].get('game_version'),source_hashes={**alignment['inputs'],'control_pack_identity':alignment['control_pack_id']})
    # Assert strict graph records and texts survived exactly, including original choices.
    final=bundle.to_dict()
    for key in ['nodes','edges','missions']:
        indexed={x['id']:x for x in final[key]}
        if any(indexed.get(x['id'])!=x for x in original[key]):raise ValueError('Strict graph changed during HF merge')
    for key,value in original['texts'].items():
        if final['texts'].get(key)!=value:raise ValueError('Original text changed during HF merge')
    new_external={(r['source_id'],r['target_id']) for r in alignment['relations'] if r['status']=='HF_ORDER_ONLY'}-set(previous_pairs)
    return bundle,{'reader_entries':missions,'default_reader_entry':missions[best],'candidate_external_pairs':len(pair_inventory),'new_hf_only_pairs_vs_baseline':len(new_external),'new_game_verified_pairs':0,'strict_graph_preserved':True}
