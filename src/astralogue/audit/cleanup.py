"""Human-reviewed, phase-based optional overlays over existing Reader edges.

Does not require a unique text-successor match in Wiki. Only existing graph edges
are rewired; every body must prove a bounded linear span and its original exit.
"""
from copy import deepcopy
from astralogue.model import Bundle,Node,Edge,digest
from astralogue.narrative.patch import validate_patch


def compile_cleanup(bundle,patches):
    from astralogue import __version__
    b=Bundle.from_dict(deepcopy(bundle.to_dict()));nodes={n.id:n for n in b.nodes}
    b.metadata['version']=__version__
    info=b.metadata['narrative'];groups={};touched=set();report={'applied':[],'deferred':[],'phases':[]}
    for patch in patches:
        validation=validate_patch(bundle,patch)
        if not validation['valid']:raise ValueError(str(validation['errors']))
        info.setdefault('patches',{})[patch['id']]={'document':deepcopy(patch),'sha256':digest(patch),
            'origin':'human_reviewed_reader_policy','game_verified':False,
            'original_reader_nodes':{nid:deepcopy(nodes[nid].__dict__) for op in patch['operations'] for nid in op.get('nodes',[])},
            'original_reader_edges':[deepcopy(e.__dict__) for e in b.edges if any(e.source in op.get('nodes',[]) or e.target in op.get('nodes',[]) for op in patch['operations'])]}
        for op in patch['operations']:
            if op['op']!='narrative_audit':raise ValueError('Expected human narrative audit patch')
            suggestion=op['suggestion'];ids=op['nodes'];after=suggestion['after']
            phases=after.get('candidate_phases',[])
            phase=after.get('phase_id') or (phases[0] if len(phases)==1 else None)
            if suggestion['operation']!='move_to_optional_interaction' or not phase:
                report['deferred'].append({'patch':patch['id'],'reason':'Operation requires explicit reconstruction plan or unique reviewed phase'});continue
            if set(ids)&touched:raise ValueError('Conflicting approved proposals overlap')
            if any(nodes[n].kind!='dialogue' for n in ids):raise ValueError('Only proven linear dialogue bodies can be moved automatically')
            outgoing={nid:[e for e in b.edges if e.source==nid] for nid in ids}
            if any(len(v)!=1 or v[0].kind!='next' or v[0].condition is not None for v in outgoing.values()):raise ValueError('Branching/conditional body needs dedicated review')
            selected=set(ids);incoming={nid:[e for e in b.edges if e.target==nid and e.source not in selected] for nid in ids}
            starts=[n for n in ids if incoming[n]]
            if len(starts)!=1:raise ValueError('Body has multiple entrances or disconnected repeated text; review instances separately')
            start=starts[0];chain=[];at=start
            if any(e.kind!='next' or e.condition is not None for e in incoming[start]):raise ValueError('Optional move would detach a conditional/choice body; dedicated phase plan required')
            while at in selected and at not in chain:chain.append(at);at=outgoing[at][0].target
            if set(chain)!=selected or at in selected:raise ValueError('Body is not one acyclic connected span')
            protected=[e for e in b.edges if e.source in selected or e.target==start]
            if any(info.get('relations',{}).get(e.id,{}).get('verified') or info.get('relations',{}).get(e.id,{}).get('evidence',{}).get('class','').startswith('GAME_VERIFIED') for e in protected):raise ValueError('Verified game control relation cannot be overwritten')
            touched.update(ids);groups.setdefault((nodes[start].mission,phase),[]).append({'patch':patch,'start':start,'tail':chain[-1],'exit':at,
                'incoming':incoming[start],'label':after.get('interaction','额外互动'),'nodes':chain,'task':nodes[start].data.get('task')})
    def edge(a,z,proof,value=None,label=None,condition=None):
        eid='audit-edge:'+digest([a,z,value])[:28]
        b.edges.append(Edge(eid,a,z,'option' if value else 'next',b.text(eid+':label',label) if label else None,condition,value))
        info.setdefault('relations',{})[eid]={'origin':'community','verified':False,'policy':'human-reviewed-phase-reader-v1','evidence':proof}
    for (mid,phase),bodies in groups.items():
        existing=[n for n in b.nodes if n.mission==mid and n.kind=='choice' and n.data.get('reader_action')=='free_exploration' and n.data.get('scene_id')==phase]
        if len(existing)>1:raise ValueError('Multiple existing phase menus require an explicit reviewed merge')
        if existing:
            menu=existing[0].id
            proof={'class':'COMMUNITY_REVIEWED','phase':phase,'patches':[x['patch']['id'] for x in bodies],
                   'game_trigger':'UNKNOWN','reader_policy':'reuse existing reviewed reading phase; no invented game trigger'}
            first_to_exit={body['start']:body['exit'] for body in bodies}
            for body in bodies:
                successor=body['exit'];seen=set()
                while successor in first_to_exit:
                    if successor in seen:raise ValueError('Optional skip loop')
                    seen.add(successor);successor=first_to_exit[successor]
                for incoming_edge in body['incoming']:
                    old=deepcopy(incoming_edge.__dict__);incoming_edge.target=successor
                    info['relations'][incoming_edge.id]={'origin':'community','verified':False,'policy':'human-reviewed-phase-reader-v1','evidence':{**proof,'prior_edge':old}}
                duplicates=[]
                for evidence in body['patch']['evidence']:
                    source=evidence.get('record',{}).get('source',{})
                    existing_source=existing[0].data.get('source',{}).get('interaction',{}).get('source',{})
                    if source.get('sha256') and source.get('sha256')==existing_source.get('sha256') and source.get('start')==existing_source.get('start'):
                        duplicates=[e for e in b.edges if e.source==menu and e.value!='main'];break
                if len(duplicates)>1:raise ValueError('Ambiguous existing optional interaction')
                tail_edge=next(e for e in b.edges if e.source==body['tail']);b.edges.remove(tail_edge);info['relations'].pop(tail_edge.id,None)
                if duplicates:
                    option=duplicates[0];at=option.target;visited=set()
                    while nodes.get(at) and nodes[at].kind=='dialogue' and at not in visited:
                        visited.add(at);out=[e for e in b.edges if e.source==at]
                        if len(out)!=1:raise ValueError('Existing optional body has unsupported control')
                        at=out[0].target
                    mark=nodes.get(at);out=[e for e in b.edges if e.source==at]
                    if not mark or mark.kind!='set' or len(out)!=1 or out[0].target!=menu:raise ValueError('Existing return/settlement is not proven')
                    old_target=option.target;option.target=body['start']
                    info['relations'][option.id]={'origin':'community','verified':False,'policy':'human-reviewed-phase-reader-v1','evidence':{**proof,'prior_target':old_target}}
                    edge(body['tail'],mark.id,proof)
                else:
                    flag=body['patch']['id']+':read';mark=flag+':mark'
                    b.metadata.setdefault('mission_initial_variables',{}).setdefault(mid,{})[flag]=False
                    b.nodes.append(Node(mark,mid,'set',data={'var':flag,'value':True}));edge(body['tail'],mark,proof);edge(mark,menu,proof)
                    edge(menu,body['start'],proof,body['patch']['id'],body['label'],{'eq':[{'var':flag},False]})
                report['applied'].append({'patch':body['patch']['id'],'nodes':body['nodes'],'menu':menu,'game_verified':False,'reused_existing_phase':True,'duplicate_source_branch_replaced':bool(duplicates)})
            report['phases'].append({'phase':phase,'menu':menu,'bodies':len(bodies),'reused':True})
            continue
        # Phase menu anchor must dominate the other selected bodies along
        # existing graph flow; numeric IDs and file order are never consulted.
        def reaches(a,z):
            seen=set();pending=[a]
            while pending:
                n=pending.pop()
                if n==z:return True
                if n not in seen:
                    seen.add(n);pending.extend(e.target for e in b.edges if e.source==n)
            return False
        anchors=[body for body in bodies if all(reaches(body['start'],other['start']) for other in bodies)]
        if len(anchors)!=1:raise ValueError('No unique graph-supported phase anchor; human phase plan required')
        anchor=anchors[0];menu='audit-phase:'+digest([mid,phase])[:24];init=menu+':enter';context=menu+':context';leave=menu+':leave'
        proof={'class':'COMMUNITY_REVIEWED','phase':phase,'patches':[x['patch']['id'] for x in bodies],
               'game_trigger':'UNKNOWN','reader_policy':'explicitly selected optional reading, once per account progress'}
        b.nodes.extend([Node(init,mid,'set',data={'var':'current_scene_id','value':phase}),
            Node(context,mid,'set',data={'var':'current_exploration_node','value':menu}),
            Node(menu,mid,'choice',data={'reader_action':'free_exploration','scene_id':phase,'scene_title':'自由活动','task':anchor['task'],'recorded_value':'main','continuation_value':'main','reader_message':'经人工审核的场景阅读策略；游戏触发契约仍未完整恢复。'}),
            Node(leave,mid,'set',data={'var':'current_exploration_node','value':None})])
        # Determine the main successor by following existing exits through other
        # removed bodies. Each successor is backed by an original graph edge.
        first_to_exit={body['start']:body['exit'] for body in bodies}
        def skip(target):
            seen=set()
            while target in first_to_exit:
                if target in seen:raise ValueError('Optional body skip would loop')
                seen.add(target);target=first_to_exit[target]
            return target
        for body in bodies:
            for incoming_edge in body['incoming']:
                old=deepcopy(incoming_edge.__dict__);incoming_edge.target=init if body is anchor else skip(body['exit'])
                info['relations'][incoming_edge.id]={'origin':'community','verified':False,'policy':'human-reviewed-phase-reader-v1',
                    'evidence':{**proof,'prior_edge':old,'prior_relation':info['relations'].get(incoming_edge.id)}}
            tail_edge=next(e for e in b.edges if e.source==body['tail']);b.edges.remove(tail_edge)
            info['relations'].pop(tail_edge.id,None)
            flag=body['patch']['id']+':read';mark=flag+':mark'
            b.metadata.setdefault('mission_initial_variables',{}).setdefault(mid,{})[flag]=False
            b.nodes.append(Node(mark,mid,'set',data={'var':flag,'value':True}))
            edge(body['tail'],mark,proof);edge(mark,menu,proof)
            edge(menu,body['start'],proof,body['patch']['id'],body['label'],{'eq':[{'var':flag},False]})
            report['applied'].append({'patch':body['patch']['id'],'nodes':body['nodes'],'menu':menu,'game_verified':False})
        edge(init,context,proof);edge(context,menu,proof);edge(menu,leave,proof,'main','推进主线');edge(leave,skip(anchor['exit']),proof)
        report['phases'].append({'phase':phase,'menu':menu,'bodies':len(bodies)})
    b.metadata['audit_cleanup']=report;return b
