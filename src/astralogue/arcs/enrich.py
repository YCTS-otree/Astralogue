"""Append identity and evidence-bound BWIKI branches to an existing Reader IR."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import re
from pathlib import Path

from astralogue.model import Node, Edge, Diagnostic, load_json, file_hash, digest
from astralogue.adapters.wiki import normalize
from astralogue.adapters.wiki.bwiki import parse_page, inline, templates, dialogue_body
from astralogue.hsr.hf_alignment import GameEvidence


def enrich(bundle, source: Path, dataset: Path, snapshots: Path, avatar_config: Path, control_pack):
    """Only Reader nodes are edited. Strict nodes, edges and texts are untouched."""
    b = bundle; mid = b.metadata['narrative']['entries']['reader']; meta = b.metadata['story_arcs'][mid]
    if (snapshots/'source-manifest.json').exists():
        for entry in load_json(snapshots/'source-manifest.json')['files']:
            path=(snapshots/entry['file']).resolve()
            if not path.is_relative_to(snapshots.resolve()) or not path.is_file() or file_hash(path)!=entry['sha256']:
                raise ValueError('BWIKI cached source hash/path conflict')
    report = {'pages': [], 'branches': [], 'skipped': [], 'conflicts': [], 'annotations': [], 'media': [], 'literal_title_retained':[]}
    b.metadata['player_reader'] = {'version': 1, 'report': report, 'arcs': [mid]}
    b.metadata['required_capabilities']=sorted(set(b.metadata.get('required_capabilities',[]))|{'reader-player-v1'})
    raw = avatar_config.read_bytes(); index = load_json(source/'resource-index.json')
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != index['files']['ExcelOutput/AvatarConfig.json']['sha']:
        raise ValueError('AvatarConfig/source version conflict')
    avatar_rows = load_json(avatar_config); avatar_rows = avatar_rows if isinstance(avatar_rows, list) else list(avatar_rows.values())
    avatars = {}
    for a in avatar_rows:
        # Stable base avatar IDs and resource tags, not a gender boolean as identity.
        if a.get('AvatarVOTag') in {'playergirl', 'playerboy'} and a.get('AvatarBaseType') == 'Warrior':
            avatars[str(a['AvatarID'])] = {'name': '星' if a['AvatarVOTag'] == 'playergirl' else '穹',
                'text_variant': 'F' if a['AvatarVOTag'] == 'playergirl' else 'M', 'source': 'AvatarConfig.json',
                'sha256': file_hash(avatar_config), 'raw': a}
    if len(avatars) != 2: raise ValueError('Base player avatar mapping ambiguous')
    b.metadata['player_reader']['avatars'] = avatars
    b.metadata['player_reader']['avatar_order'] = sorted(avatars,key=lambda k:avatars[k]['text_variant']!='F')
    b.metadata['player_reader']['game_source'] = load_json(source/'source.json')
    narrative=b.metadata['narrative']
    narrative['game']='HSR';narrative['game_version']=b.metadata['player_reader']['game_source']['game_version']
    narrative['source_hashes']={**narrative.get('source_hashes',{}),**b.metadata.get('inputs',{}),
        'player:avatar_config':file_hash(avatar_config),
        **{'player:bwiki:'+t['title']:file_hash(snapshots/(t['title']+'.json')) for t in meta['plan']['tasks'] if (snapshots/(t['title']+'.json')).exists()},
        **{'player:hf:'+t['hf']:file_hash(dataset/t['hf']) for t in meta['plan']['tasks']}}
    sentences = {r['TalkSentenceID']: r for r in load_json(source/'ExcelOutput/TalkSentenceConfig.json') if 'TalkSentenceID' in r}
    chs = load_json(source/'TextMap/TextMapCHS.json'); text_index = defaultdict(list);nickname_index=defaultdict(list)
    text_hashes={'catalog_sha256':file_hash(source/'ExcelOutput/TalkSentenceConfig.json'),'textmap_sha256':file_hash(source/'TextMap/TextMapCHS.json')}
    for sid, r in sentences.items():
        text = chs.get(str(r.get('TalkSentenceText', {}).get('Hash')))
        if text:
            text_index[normalize(text)].append(sid)
            if '{NICKNAME}' in text:nickname_index[normalize(text.replace('{NICKNAME}','开拓者'))].append((sid,text))
    game = GameEvidence(control_pack, source)
    raw_groups = []
    relevant_ids = {x for t in meta['plan']['tasks'][:2] for x in t['main_ids']}
    def inspect(value, file, pointer='',sequence=None):
        if isinstance(value,dict):
            if isinstance(value.get('TaskList'),list):sequence=value
            if isinstance(value.get('OptionList'),list):
                raw_groups.append({'node':file+pointer,'ids':[o.get('TalkSentenceID') for o in value['OptionList']],
                                   'source':{'file':file,'pointer':pointer,'sha256':file_hash(source/file)},'raw':value,'sequence':sequence})
            for k,v in value.items():inspect(v,file,pointer+'/'+k,sequence)
        elif isinstance(value,list):
            for i,v in enumerate(value):inspect(v,file,pointer+'/'+str(i),sequence)
    for main in sorted(relevant_ids):
        for folder in [source/'Story/Mission'/main,source/'Config/Level/Mission'/main]:
            for path in sorted(folder.rglob('*.json')) if folder.exists() else []:
                inspect(load_json(path),path.relative_to(source).as_posix())
    raw_option_ids={sid for g in raw_groups for sid in g['ids']}
    nodes = {n.id: n for n in b.nodes}
    relations = b.metadata['narrative']['relations']

    def add_edge(a, z, proof, *, value=None, text=None, cls='WIKI_ALIGNED'):
        eid = a+':enriched:'+digest([z, value])[:20]
        b.edges.append(Edge(eid, a, z, 'option' if value is not None else 'next', text=text, value=value))
        relations[eid] = {'origin': 'inferred', 'verified': False, 'evidence_verified': False,
                          'policy': 'bwiki-reader-v1', 'evidence': {'class': cls, **proof}}
    def line(nid, row, target, task, proof, candidates=None):
        candidates = candidates if candidates is not None else text_index.get(normalize(row['text']), [])
        sid = candidates[0] if len(candidates) == 1 else None
        text = chs[str(sentences[sid]['TalkSentenceText']['Hash'])] if sid else row['text']
        speaker = row['speaker']; original = sentences.get(sid, {})
        speaker_hash = str(original.get('TextmapTalkSentenceName', {}).get('Hash'))
        name = chs.get(speaker_hash, speaker)
        data = {'task': task, 'sentence_id': sid, 'content_origin': 'GAME' if sid else 'WIKI_ALIGNED',
                'alignment_candidates': candidates, 'speaker_identity': {'display_name': name,
                'name_hash': speaker_hash if speaker_hash != 'None' else None, 'entity_id': None,
                'anonymous_id': 'speaker:'+speaker_hash if speaker_hash != 'None' else 'wiki:'+digest([proof, speaker])[:16],
                'candidates': [], 'verification': 'display_only', 'presentation': 'original_display'}}
        n = Node(nid, mid, 'dialogue', b.text(nid+':text', text), b.text(nid+':speaker', name), data)
        b.nodes.append(n); nodes[nid] = n; add_edge(nid, target, proof)
        b.source_refs.append({'node': nid, **proof, 'raw': row})
        return nid

    for boundary in meta['task_boundaries']:
        task = boundary['task']; filename = boundary['file']; hf = load_json(dataset/filename)['story']
        page_path = snapshots/(boundary['title']+'.json')
        if not page_path.exists(): continue
        page = parse_page(page_path); report['pages'].append({k: page[k] for k in ['title','page_id','revision_id','url','snapshot_sha256','retrieval']})
        proof = report['pages'][-1];proof['stage_directions_parsed']=len(page['stage_directions'])
        rows = {r['index']: r for r in meta['rows'] if r['file'] == filename}
        pairs_data = game.collect(boundary['title']); owned = set(pairs_data['owned_ids'])
        pairs = {(p['source'], p['target']) for p in pairs_data['pairs']}
        for choice in page['choices']:
            opts = choice['options']
            if len(opts) < 2 or choice['unknown']:
                if choice['unknown']:report['skipped'].append({'page':page['title'],'position':choice['start'],'reason':'unsupported template content retained','unknown':choice['unknown']})
                continue
            matches = [i for i, row in enumerate(hf) if normalize(row['content']) == normalize(opts[0]['label']['text'])]
            valid = []
            for i in matches:
                first = opts[0]['body']; end = i+len(first)
                if end >= len(hf): continue
                if any(normalize(hf[i+1+j]['content']) != normalize(row['text']) for j,row in enumerate(first)): continue
                root = rows.get(i, {}).get('node')
                if not root or nodes[root].kind != 'choice': continue  # preserve complete native projections
                # Explicit next dialogue outside the template is the merge anchor.
                suffix = page['wikitext'][choice['end']:]
                after = re.search(r'^\*([^：\n]+)：(.*)$', suffix, flags=re.M)
                next_choice = next((c for c in page['choices'] if c['start']>=choice['end']),None)
                if next_choice and (not after or next_choice['start'] < choice['end']+after.start()):
                    next_text=next_choice['options'][0]['label']['text']
                else:next_text=inline(after[2])['text'] if after else None
                if next_text is None or normalize(next_text) != normalize(hf[end+1]['content']): continue
                if not rows.get(end+1, {}).get('node'): continue
                valid.append((i, end, root, rows[end+1]['node']))
            if len(valid) != 1:
                report['skipped'].append({'page': page['title'], 'position': choice['start'], 'reason': 'no unique exact source span/merge or native projection already retained'}); continue
            i, end, root, merge = valid[0]; n = nodes[root]
            # Crosscheck option IDs against a single actual raw OptionList.
            groups = []
            for group in list(game.option_groups.values())+raw_groups:
                ids = group['ids']
                mapped=[]
                for o in opts:
                    matches=[sid for sid in ids if sid in sentences and normalize(chs[str(sentences[sid]['TalkSentenceText']['Hash'])]) == normalize(o['label']['text'])]
                    if len(matches)!=1:break
                    mapped.append(matches[0])
                if len(mapped)==len(opts):groups.append((group,mapped))
            groups = {tuple(mapped):(g,mapped) for g,mapped in groups}
            group,ids = next(iter(groups.values())) if len(groups)==1 else (None,[None]*len(opts))
            branch_proof = {**proof, 'template_position': choice['start'], 'raw_template': choice['raw'], 'game_option_group': group}
            # Some BWIKI templates contain the two optional questions; the
            # third game option is the immediately following "continue" line.
            # Restore the loop only when the raw script explicitly returns
            # each question event to the same WaitCustomString loop entry.
            inquiry=None
            if group and group.get('sequence',{}).get('IsLoop') and group.get('raw',{}).get('HideSelected'):
                missing=[sid for sid in group['ids'] if sid not in ids]
                seq=group['sequence']['TaskList'];waiting=[v.get('CustomString',{}).get('Value') for v in seq if v.get('$type','').endswith('.WaitCustomString')]
                next_node=nodes.get(merge);next_edges=[e for e in b.edges if e.source==merge]
                if len(missing)==1 and len(waiting)==1 and next_node and next_node.kind=='choice' and len(next_edges)==1 and normalize(chs[str(sentences[missing[0]]['TalkSentenceText']['Hash'])])==normalize(hf[end+1]['content']):
                    resource=load_json(source/group['source']['file']);sequences=resource.get('OnStartSequece',[])
                    routes=[]
                    for sid in ids:
                        trigger=next(o.get('TriggerCustomString') for o in group['raw']['OptionList'] if o.get('TalkSentenceID')==sid)
                        found=[s for s in sequences if s.get('TaskList') and s['TaskList'][0].get('$type','').endswith('.WaitCustomString') and s['TaskList'][0].get('CustomString',{}).get('Value')==trigger]
                        if len(found)!=1 or not found[0]['TaskList'][-1].get('$type','').endswith('.TriggerCustomString') or found[0]['TaskList'][-1].get('CustomString',{}).get('Value')!=waiting[0]:break
                        routes.append(found[0])
                    if len(routes)==len(ids):inquiry={'continuation_id':missing[0],'routes':routes,'loop_event':waiting[0]}
            # Refuse a contradicting GAME_VERIFIED local choice; never touch Strict edges.
            old = [e for e in b.edges if e.source == root]
            if any(relations.get(e.id, {}).get('evidence', {}).get('class') == 'GAME_VERIFIED_LOCAL' for e in old):
                report['conflicts'].append({'node': root, 'reason': 'native projection takes priority'}); continue
            b.edges = [e for e in b.edges if e.source != root]
            for e in old: relations.pop(e.id, None)
            n.data.update(reader_action='bwiki_choice', reader_message='BWIKI 固定修订的选项、回应与汇合；Reader 来源，非完整原生任务执行。',
                          source_option_ids={o['value']:sid for o,sid in zip(opts,ids)}, recorded_value=opts[0]['value'], bwiki=proof)
            checked_pairs = 0
            for j, o in enumerate(opts):
                branch_exit=merge
                flag=None
                if inquiry:
                    flag=root+':asked:'+o['value'];mark=flag+':mark'
                    b.metadata.setdefault('mission_initial_variables',{}).setdefault(mid,{})[flag]=False
                    b.nodes.append(Node(mark,mid,'set',data={'var':flag,'value':True}))
                    add_edge(mark,root,{**branch_proof,'inquiry_loop':inquiry},cls='GAME_CONTROL_LOOP_WIKI_TEXT')
                    branch_exit=mark
                if j == 0:
                    target = old[0].target  # identical HF default path remains auditable
                    if inquiry:
                        tail=nodes[rows[end]['node']]
                        exits=[e for e in b.edges if e.source==tail.id and e.target==merge]
                        if len(exits)!=1:raise ValueError('Optional question body exit ambiguous')
                        exits[0].target=branch_exit
                else:
                    target = branch_exit
                    for k, row in reversed(list(enumerate(o['body']))):
                        candidates = text_index.get(normalize(row['text']), [])
                        local = [x for x in candidates if x in owned]
                        if local: candidates = local
                        target = line(root+':bwiki:'+o['value']+':'+str(k), row, target, task, branch_proof, candidates)
                label_key = b.text(root+':bwiki-option:'+o['value'], chs[str(sentences[ids[j]]['TalkSentenceText']['Hash'])] if ids[j] else o['label']['text'])
                add_edge(root, target, branch_proof, value=o['value'], text=label_key)
                if inquiry:
                    b.edges[-1].condition={'eq':[{'var':flag},False]}
                if o['body'] and ids[j]:
                    candidates = text_index.get(normalize(o['body'][0]['text']), [])
                    checked_pairs += sum((ids[j], x) in pairs for x in candidates)
            if inquiry:
                sid=inquiry['continuation_id'];value='continue';old_next=[e for e in b.edges if e.source==merge]
                # Preserve the HF continue utterance as the selected player's
                # speech, without asking the same choice for a second time.
                echo=nodes[merge];echo.kind='dialogue';echo.text=b.text(merge+':selected-game-option',chs[str(sentences[sid]['TalkSentenceText']['Hash'])])
                echo.speaker=b.text(merge+':player-speaker','开拓者')
                echo.data.update(content_origin='GAME',sentence_id=sid,selected_option_echo=True)
                old_next[0].kind='next';old_next[0].text=None;old_next[0].value=None
                n.data.update(reader_action='optional_inquiry',continuation_value=value,
                    reader_message='原控制脚本证明：问题可选择一次并返回；继续选项离开对话。回应文本/顺序由 BWIKI 补足，仍是 Reader 投影。')
                n.data['source_option_ids'][value]=sid
                add_edge(root,merge,{**branch_proof,'inquiry_loop':inquiry},value=value,text=b.text(root+':continue',chs[str(sentences[sid]['TalkSentenceText']['Hash'])]))
            report['branches'].append({'page': page['title'], 'node': root, 'hf_index': i, 'merge': merge,
                'options': len(opts)+(1 if inquiry else 0), 'added_options': len(opts)-1,
                'loop_recovered':bool(inquiry),'option_ids': ids+([inquiry['continuation_id']] if inquiry else []), 'game_crosschecked_first_response_pairs': checked_pairs,
                'default_span': [i,end], 'source': proof, 'native_control_promoted': False})
        # Context-bound nickname repairs. Require a game variable text AND a local control neighbor.
        variables = [(sid, chs[str(r['TalkSentenceText']['Hash'])]) for sid,r in sentences.items()
                     if '{NICKNAME}' in chs.get(str(r.get('TalkSentenceText',{}).get('Hash')), '')]
        for i,row in enumerate(hf):
            nid = rows.get(i, {}).get('node')
            if not nid: continue
            n = nodes[nid]
            if rows[i]['source'] == 'GAME': continue
            candidate = [(sid,text) for sid,text in variables if normalize(text.replace('{NICKNAME}','开拓者')) == normalize(row['content'])]
            left = rows.get(i-1, {}).get('id'); right = rows.get(i+1, {}).get('id')
            candidate = [(sid,text) for sid,text in candidate if (left,sid) in pairs or (sid,right) in pairs or sid in raw_option_ids or
                         (i>0 and nodes.get(rows.get(i-1,{}).get('node'),'') and getattr(nodes.get(rows.get(i-1,{}).get('node')),'data',{}).get('text_parameters'))]
            if len(candidate) != 1: continue
            sid,text = candidate[0]; annotations = []
            for m in re.finditer(re.escape('开拓者'), row['content']):
                # A reversible substitution proves the whole string, no global title replacement.
                if row['content'][:m.start()]+'{NICKNAME}'+row['content'][m.end():] == text:
                    annotations.append({'start':m.start(),'end':m.end(),'literal':'开拓者','parameter':'nickname',
                                        'game_sentence_id':sid,'game_text':text,'evidence':proof})
            if annotations:
                n.data['text_parameters'] = annotations; report['annotations'].append({'node':nid,'id':sid,'count':len(annotations)})
        # Inline editorial/media notes, separate from dialogue. Retain the real resource structure.
        for line_match in re.finditer(r'^\*([^：\n]+)：(.*)$', page['wikitext'], re.M):
            parsed = inline(line_match[2])
            if not parsed['media'] or parsed['unknown']: continue
            retained=inline(re.sub(r'\{\{黑幕\|([^{}]+)\}\}',r'\1',line_match[2]))['text']
            hits = [i for i,row in enumerate(hf) if normalize(row['content']) in {normalize(parsed['text']),normalize(retained)}]
            if len(hits) != 1: continue
            nid = rows.get(hits[0], {}).get('node')
            if not nid or nodes[nid].kind != 'dialogue': continue
            outgoing = [e for e in b.edges if e.source == nid]
            if len(outgoing) != 1: continue
            tail = outgoing[0].target
            # Remove an embedded editor note only in this exact source-bound
            # occurrence. The untouched HF string remains in source_refs.
            nodes[nid].text=b.text(nid+':without-inline-editor-note',parsed['text'])
            for j,media in reversed(list(enumerate(parsed['media']))):
                report['media'].append({'node':nid,'resource':media,'source':proof,'position':line_match.start()})
                if not media.get('display'): continue
                note = nid+':media:'+str(j)
                tail = line(note, {'text':media['display'],'speaker':'Wiki 舞台/资源注释'}, tail, task, {**proof,'media':media}, [])
                nodes[note].data['content_kind'] = 'stage_direction'
            outgoing[0].target = tail
        # Locate the identity event by the exact preceding dialogue in the page, not startup.
        marker = re.search(r':\{\{颜色\|描述\|启用载体「星」或「穹」\}\}', page['wikitext'])
        if marker:
            prior = list(re.finditer(r'^\*([^：\n]+)：(.*)$', page['wikitext'][:marker.start()], re.M))[-1]
            anchor = inline(prior[2])['text']; hits = [i for i,row in enumerate(hf) if normalize(row['content']) == normalize(anchor)]
            if len(hits) != 1: raise ValueError('Identity story anchor ambiguous')
            nid = rows[hits[0]]['node']; outgoing = [e for e in b.edges if e.source == nid]
            if len(outgoing) != 1: raise ValueError('Identity story anchor has branching control')
            init = nid+':player-identity'; target = outgoing[0].target; outgoing[0].target = init
            n = Node(init, mid, 'choice', data={'player_action':'initialize','task':task,'bwiki':proof})
            b.nodes.append(n); nodes[init] = n
            add_edge(init, target, {**proof,'event_position':marker.start()}, value='confirm', text=b.text(init+':confirm','身份认证完成'))
            idle=next((t for t in templates(page['wikitext']) if t['name']=='折叠' and t['params'].get('标题')=='彩蛋' and t['start']>marker.start()),None)
            if idle:
                idle_rows,_=dialogue_body(idle['params'].get('内容',''))
                hits=[]
                for j in range(len(hf)-len(idle_rows)+1):
                    if idle_rows and all(normalize(hf[j+k]['content'])==normalize(v['text']) for k,v in enumerate(idle_rows)):hits.append(j)
                if len(hits)==1:
                    first=hits[0];last=first+len(idle_rows)-1
                    menu=init+':idle-extras'
                    b.nodes.append(Node(menu,mid,'choice',data={'task':task,'reader_action':'optional_idle_dialogue',
                        'reader_message':'BWIKI 将以下对白标为等待载体选择时的可选彩蛋；可查看转录或直接继续，不表示全部对白在同一路径发生。','recorded_value':'view'}))
                    next(e for e in b.edges if e.source==init).target=menu
                    for value,z,label in [('view',rows[first]['node'],'查看可选等待对白'),('skip',rows[last+1]['node'],'完成身份认证，继续剧情')]:
                        add_edge(menu,z,{**proof,'fold_position':idle['start']},value=value,text=b.text(menu+':'+value,label),cls='WIKI_OPTIONAL_IDLE')
                    report['optional_idle']={'node':menu,'source_span':[first,last],'source':proof}
            report['identity'] = {'node':init,'after_hf_index':hits[0],'source':proof,
                'control_evidence':{'file':'Config/Level/Mission/1000101/MissionInfo_1000101.partial.json',
                                    'sha256':file_hash(source/'Config/Level/Mission/1000101/MissionInfo_1000101.partial.json'),
                                    'finish_type':'CreateCharacter'}, 'ui_policy':'Reader confirmation; no game account mutation'}
    if 'identity' not in report: raise ValueError('Identity event not found')
    # Keep structured anonymous identities even where the original display is ???.
    for n in b.nodes:
        if n.mission != mid or n.kind != 'dialogue' or 'speaker_identity' in n.data: continue
        display = b.texts.get(n.speaker,{}).get('CHS', '未标注角色')
        sid = n.data.get('sentence_id'); raw = sentences.get(sid, {})
        name_hash = raw.get('TextmapTalkSentenceName',{}).get('Hash')
        n.data['speaker_identity'] = {'display_name':display,'name_hash':name_hash,'entity_id':None,
            'anonymous_id':'source:'+digest([n.id,n.speaker])[:16],
            'candidates':[],'verification':'display_only','presentation':'original_display'}
    for n in b.nodes:
        if n.mission!=mid or n.data.get('content_origin')!='COMMUNITY_TRANSCRIPT' or n.data.get('text_parameters'):continue
        # A parameter can be proved even where several IDs share the identical
        # variable layout. Do not choose an ID: retain every candidate and
        # require unanimous, reversible, full-string parameter placement.
        keys=[(None,n.text)] if n.text else [(e.value,e.text) for e in b.edges if e.source==n.id and e.text]
        for option,key in keys:
            text=b.texts.get(key,{}).get('CHS','')
            if '开拓者' not in text:continue
            candidates=nickname_index.get(normalize(text),[])
            layouts=[]
            for sid,template in candidates:
                positions=[(m.start(),m.end()) for m in re.finditer('开拓者',text)
                           if normalize(text[:m.start()]+'{NICKNAME}'+text[m.end():])==normalize(template)]
                layouts.append(positions)
            if not layouts or not layouts[0] or any(layout!=layouts[0] for layout in layouts):continue
            ids=[sid for sid,_ in candidates]
            proof={'class':'EXACT_GAME_PARAMETER_LAYOUT','game_source':b.metadata['player_reader']['game_source'],
                   **text_hashes,
                   'candidates':[{'id':sid,'template':template} for sid,template in candidates],
                   'id_selected':False,'node':n.id,'task':n.data.get('task')}
            for start,end in layouts[0]:
                n.data.setdefault('text_parameters',[]).append({'start':start,'end':end,'literal':'开拓者',
                    'parameter':'nickname','option':option,'language':'CHS','game_sentence_ids':ids,'evidence':proof})
            report['annotations'].append({'node':n.id,'id':ids[0] if len(ids)==1 else None,'candidate_ids':ids,
                'count':len(layouts[0]),'variable_layout_verified':True,'dialogue_id_assigned':False})
    for n in b.nodes:
        if n.mission!=mid or n.data.get('content_origin')!='COMMUNITY_TRANSCRIPT' or n.data.get('text_parameters'):continue
        keys=[n.text] if n.text else [e.text for e in b.edges if e.source==n.id and e.text]
        for key in keys:
            if '开拓者' in b.texts.get(key,{}).get('CHS',''):
                report['literal_title_retained'].append({'node':n.id,'text_hash':digest(b.texts[key]['CHS']),
                    'diagnostic':'literal retained; no verified nickname parameter at this occurrence'})
    return b
