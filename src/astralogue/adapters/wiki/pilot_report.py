"""Offline source manifest and seven-task structure comparison; no text-coverage claims."""
from pathlib import Path
from .pilot import Pilot, CHAPTER
from astralogue.model import load_json, file_hash
from astralogue.adapters.wiki import normalize
from astralogue.storypack import StoryPack


def report(root: Path, pack: Path, dataset: Path):
    p=Pilot(root)
    try:
        result={'queue':p.status(),'tasks':[],'network_requests':[],
                'scope':'Chapter 100001 only; optional classification is Wiki evidence, not world-state proof'}
        result['network_requests']=[dict(r) for r in p.db.execute('SELECT * FROM requests ORDER BY at')]
        robots=p.root/'robots.txt'
        result['robots']={'sha256':file_hash(robots),'file':str(robots)} if robots.exists() else None
        with StoryPack(pack) as sp:
            mid=next(iter(sp.metadata['story_arcs']));tasks=sp.metadata['story_arcs'][mid]['plan']['tasks']
            for task in tasks:
                row=next((r for r in result['queue']['pages'] if r['title'].replace('•','·')==task['title'].replace('•','·')),None)
                if not row or row['status']!='VALIDATED':
                    result['tasks'].append({'title':task['title'],'status':'missing_or_unparsed'});continue
                parsed=load_json(p.root/row['parsed']);hf=load_json(dataset/task['hf'])['story']
                hf_text={normalize(r['content']) for r in hf}
                optional=[x for s in parsed['sections'] for x in s['interactions'] if x['kind']=='optional_dialogue']
                result['tasks'].append({'title':task['title'],'page_id':row['page_id'],'revision_id':row['revision_id'],
                    'sha256':row['sha256'],'hf_source':task['hf'],'hf_items':len(hf),'sections':len(parsed['sections']),
                    'optional_folds':len(optional),'optional_lines':sum(len(x['rows']) for x in optional),
                    'optional_text_also_in_hf':sum(normalize(r['text']) in hf_text for x in optional for r in x['rows']),
                    'unclassified_folds':sum(x['kind']=='unknown' for s in parsed['sections'] for x in s['interactions']),
                    'choices':len(parsed['choices']), 'game_control_replaced':False,
                    'warning':'Text overlap is not a proof of path/order; unclassified investigation retained'})
        return result
    finally:p.close()
