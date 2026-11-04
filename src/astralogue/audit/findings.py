"""Exact-source discovery of optional folds already on the default Reader path."""
import json
from pathlib import Path
from astralogue.adapters.wiki.bwiki import parse_page
from astralogue.adapters.wiki.scenes import classify_page
from astralogue.adapters.wiki import normalize
from astralogue.arcs.session import ArcSession
from astralogue.player import ProfileEvent
from astralogue.runtime import DialogueEvent,ChoiceEvent,EndEvent
from astralogue.storypack import StoryPack
from astralogue.model import canonical,digest


def discover(store,pack_path:Path,page_path:Path):
    wiki=parse_page(page_path);scene_data=classify_page(wiki);findings=[]
    with StoryPack(pack_path) as pack:
        mid=next(iter(pack.metadata['story_arcs']));arc=pack.metadata['story_arcs'][mid];stop=arc['task_boundaries'][0]['exit']
        rt=ArcSession(pack,mid);path=[]
        for _ in range(2000):
            if rt.state.node==stop:break
            e=rt.next()
            if isinstance(e,ProfileEvent):
                rt.identity_input({'avatar':next(iter(e.avatars)),'avatar_confirm':'confirm','name':'审计档案','name_confirm':'confirm'}[e.stage]);continue
            n=pack.node(e.node)
            if isinstance(e,DialogueEvent):path.append({'node':n.id,'text':pack.text(n.text,'CHS'),'speaker':pack.text(n.speaker,'CHS'),'data':n.data})
            elif isinstance(e,ChoiceEvent):
                available={o.value for o in e.options};value='main' if 'main' in available else n.data.get('continuation_value')
                if value not in available:value=n.data.get('recorded_value')
                if value not in available:value=e.options[0].value
                rt.choose(value)
            else:raise ValueError('Audit default path blocked: '+repr(e))
        else:raise ValueError('Audit path exceeded bounded traversal')
        scenes={s['id']:{'title':s['title'],'start':s['start'],'end':s['end']} for s in scene_data['sections']}
        for scene in scene_data['sections']:
            for item in scene['interactions']:
                if item['kind']!='optional_dialogue':continue
                matches=[]
                for row in item['rows']:
                    matches.extend(n for n in path if normalize(n['text'])==normalize(row['text']))
                if not matches:continue
                matches=list({n['node']:n for n in matches}.values())
                context={'task':arc['plan']['tasks'][0],'chapter':arc['plan']['title'],
                    'instances':{str(i):n for i,n in enumerate(matches)},'scenes':scenes,
                    'evidence':{'wiki':{'page_id':wiki['page_id'],'revision_id':wiki['revision_id'],'sha256':wiki['snapshot_sha256'],
                        'source':item['source'],'section':scene['id'],'label':item['label']},
                        'graph':{'pack_id':pack.metadata['pack_id'],'source_hashes':pack.metadata['narrative'].get('source_hashes',{}),'path':'actual recorded Reader traversal; optional inquiry menus skipped'}},
                    'nearby_path':path[max(0,path.index(matches[0])-3):path.index(matches[-1])+4]}
                suggestion={'operation':'move_to_optional_interaction','instances':list(context['instances']),'targets':[],
                    'evidence':['wiki','graph'],'before':{'default_path_nodes':[m['node'] for m in matches]},
                    'after':{'candidate_phases':[scene['id']],'interaction':item['label'],'trigger_condition':'UNKNOWN','repeat_policy':'UNKNOWN'},
                    'conflicts':['Exact text may have multiple placements; phase attachment and all incoming/outgoing edges need review'] if len(matches)>len(item['rows']) else [],
                    'unknowns':['Exact world-state trigger and phase timing are not established by the extra-dialogue label'],
                    'rationale':'BWIKI explicitly labels this fold extra dialogue, while exact text occurs on the current non-exploration Reader path.'}
                pid=digest(['source-evidence-audit-v1',context,suggestion]);payload={'proposal_version':1,'context_hash':digest(context),'context':context,
                    'suggestion':suggestion,'status':'pending','origin':'DETERMINISTIC_SOURCE_CROSSCHECK','game_verified':False}
                store.db.execute('INSERT OR IGNORE INTO proposals(id,job,payload) VALUES(?,?,?)',(pid,None,canonical(payload)))
                findings.append({'proposal':pid,'label':item['label'],'default_path_nodes':[m['node'] for m in matches],'phase_candidates':[scene['id']]})
        store.db.commit()
        result={'default_dialogue_instances':len(path),'optional_findings':findings,'suspect_instances':len({n for f in findings for n in f['default_path_nodes']}),
                'independent_evidence':'Wiki explicit extra-fold label plus exact original graph text; trigger unknown',
                'human_approved':0,'applied':0,'path':path,'audit_edges':rt.traversal}
        store.setting('first_task_findings',result);return result
