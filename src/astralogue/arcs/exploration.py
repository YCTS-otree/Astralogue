"""Compile explicit Wiki optional folds to ordinary Reader choice/set/return edges.

This is a transcription browsing policy, not proof of game-world availability.
Unparsed folds and ambiguous anchors remain diagnostics instead of guessed flow.
"""
from pathlib import Path
import re
from astralogue.adapters.wiki.bwiki import parse_page, inline
from astralogue.adapters.wiki.scenes import classify_page
from astralogue.adapters.wiki import normalize
from astralogue.model import Node, Edge, digest


def compile_exploration(bundle, snapshots: list[Path]):
    from astralogue import __version__
    b = bundle; mid = b.metadata['narrative']['entries']['reader']
    if 'free_exploration' in b.metadata: raise ValueError('Exploration already compiled; rebuild from original pack')
    b.metadata['version']=__version__
    arc = b.metadata['story_arcs'][mid]; nodes = {n.id:n for n in b.nodes}
    relations = b.metadata['narrative']['relations']; report = {'scenes':[], 'unconnected':[], 'removed_from_default':0}
    b.metadata['free_exploration'] = {'version':1,'policy':'BWIKI optional reading; unknown game availability is not asserted', 'report':report}

    def edge(a,z,proof,value=None,label=None,condition=None):
        eid = a+':exploration:'+digest([z,value])[:20]
        b.edges.append(Edge(eid,a,z,'option' if value else 'next',b.text(eid+':label',label) if label else None,condition,value))
        relations[eid] = {'origin':'inferred','verified':False,'policy':'bwiki-optional-reader-v1',
                          'evidence':{'class':'WIKI_ALIGNED',**proof}}

    for path in snapshots:
        page = parse_page(path); classified = classify_page(page)
        tasks = [(i,t) for i,t in enumerate(arc['plan']['tasks']) if t['title']==page['title'] or t['title'].replace('·','•')==page['title']]
        if len(tasks)!=1: continue
        task,t = tasks[0]; rows = [r for r in arc['rows'] if r['file']==t['hf'] and r.get('node')]
        by_index = {r['index']:r['node'] for r in rows}
        def content(nid):
            n=nodes[nid]
            key=n.text
            return normalize(b.texts.get(key,{}).get('CHS',''))
        used=set()
        for section in classified['sections']:
            for item in section['interactions']:
                if item['kind']!='optional_dialogue' or not item['rows'] or item['unknown']:
                    report['unconnected'].append({'id':item['id'],'label':item['label'],'reason':'unknown role/condition or unsupported body','source':item['source']});continue
                end=item['source']['start']+len(item['source']['raw'])
                suffix=page['wikitext'][end:section['end']]
                # Only an immediately following nonfold dialogue is an anchor.
                m=re.search(r'^\*([^：\n]+)：(.*)$',suffix,re.M)
                if not m or '{{折叠' in suffix[:m.start()] or '{{剧情选项' in suffix[:m.start()]:
                    report['unconnected'].append({'id':item['id'],'label':item['label'],'reason':'no unambiguous local continuation','source':item['source']});continue
                anchor=normalize(inline(m[2])['text'])
                matches=[r for r in rows if content(r['node'])==anchor and nodes[r['node']].kind=='dialogue']
                if len(matches)!=1 or matches[0]['node'] in used:
                    report['unconnected'].append({'id':item['id'],'label':item['label'],'reason':'ambiguous/shared source anchor','source':item['source']});continue
                target=matches[0]['node']; index=matches[0]['index']; span=[]
                first=index-len(item['rows'])
                if all(first+j in by_index and content(by_index[first+j])==normalize(r['text']) for j,r in enumerate(item['rows'])):
                    span=[by_index[first+j] for j in range(len(item['rows']))]
                    # Only remove a simple linear default span, never a game choice.
                    if any(nodes[n].kind!='dialogue' or len([e for e in b.edges if e.source==n])!=1 for n in span):continue
                start=span[0] if span else target
                incoming=[e for e in b.edges if e.target==start]
                if not incoming or any(nodes[e.source].mission!=mid or relations.get(e.id,{}).get('evidence',{}).get('class','').startswith('GAME_VERIFIED') for e in incoming):
                    report['unconnected'].append({'id':item['id'],'reason':'native relation or missing entry'});continue
                menu=item['id']+':menu';init=menu+':enter';context=menu+':context';leave=menu+':leave';flag=item['id']+':read';mark=menu+':complete'
                proof={'page':page['url'],'revision_id':page['revision_id'],'sha256':page['snapshot_sha256'],
                       'section':section['id'],'interaction':item,'reader_policy':'optional source content, once per reading; game repeatability unknown'}
                b.metadata.setdefault('mission_initial_variables',{}).setdefault(mid,{})[flag]=False
                b.nodes.extend([Node(init,mid,'set',data={'var':'current_scene_id','value':section['id']}),
                    Node(context,mid,'set',data={'var':'current_exploration_node','value':menu}),
                    Node(leave,mid,'set',data={'var':'current_exploration_node','value':None}),
                    Node(menu,mid,'choice',data={'reader_action':'free_exploration','task':task,
                        'scene_id':section['id'],'scene_title':section['title'],'interaction_id':item['id'],
                        'recorded_value':'main','continuation_value':'main','reader_message':'可选互动来自 BWIKI；当前可用性与一次性阅读为 Reader 策略，非原生世界状态。',
                        'availability':'source_section_only; game_condition_unknown','source':proof}),
                    Node(mark,mid,'set',data={'var':flag,'value':True})])
                for e in incoming:
                    previous=relations.pop(e.id,None);old=e.target;e.target=init
                    relations[e.id]={'origin':'inferred','verified':False,'policy':'bwiki-optional-reader-v1',
                                     'evidence':{'class':'WIKI_ALIGNED',**proof,'prior_relation':previous,'prior_target':old}}
                edge(init,context,proof);edge(context,menu,proof);edge(menu,leave,proof,'main','推进主线：'+section['title']);edge(leave,target,proof)
                optional=mark
                for j,row in reversed(list(enumerate(item['rows']))):
                    nid=item['id']+':line:'+str(j)
                    original=nodes[span[j]] if span else None
                    b.nodes.append(Node(nid,mid,'dialogue',original.text if original else b.text(nid+':text',row['text']),original.speaker if original else b.text(nid+':speaker',row['speaker']),
                        {**(original.data if original else {}),'task':task,'content_origin':original.data.get('content_origin','WIKI_ALIGNED') if original else 'WIKI_ALIGNED','exploration_interaction':item['id'],'source':item['source']}))
                    b.source_refs.append({'node':nid,'source':proof,'raw':row});edge(nid,optional,proof);optional=nid
                edge(menu,optional,proof,'explore',item['label'],{'eq':[{'var':flag},False]});edge(mark,menu,proof)
                if span:
                    # Retain the originals as archival nodes and their source evidence.
                    report['removed_from_default']+=len(span)
                report['scenes'].append({'menu':menu,'scene':section['id'],'task':task,'label':item['label'],
                    'optional_lines':len(item['rows']),'old_default_span':span,'main_target':target,'source':proof})
                used.add(target)
    return report
