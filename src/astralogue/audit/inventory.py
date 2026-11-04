"""Deterministic traversal of existing narrative sources, never credentials or ASB blocks."""
import hashlib
import json
from pathlib import Path
import sqlite3
from astralogue.model import canonical,digest,file_hash,load_json
from .store import AuditStore


def source_files(root):
    paths=set()
    for folder in ['data/raw','data/external/hf-trailblaze/missions','data/external/hf-trailblaze/addition','docs/patches','data/patches','data/staging/bwiki']:
        p=root/folder
        if p.exists():paths.update(p.rglob('*.json'))
    for pattern in ['data/staging/*.ir.json','data/staging/*.patch.json','data/staging/hf-aligned/*.json','data/packs/*.storypack','data/*archive*.sqlite','data/staging/animestudio/**/*.json','data/staging/native-index.sqlite','data/staging/bwiki-pilot/cache/*.json','data/staging/wiki/*.json']:
        paths.update(root.glob(pattern))
    return sorted(p for p in paths if not p.name.endswith('.parsed.json'))


def kind_for(path):
    n=path.name
    if n=='TalkSentenceConfig.json':return 'dialogue_catalog'
    if n.startswith('TextMap'):return 'textmap_only'
    if n.endswith('.ir.json'):return 'ir_representation'
    if n.endswith('.storypack'):return 'storypack'
    if 'archive' in n:return 'archive'
    if n=='native-index.sqlite':return 'native_resource_index'
    return 'source_instance'


def traverse(store:AuditStore,root:Path):
    root=root.resolve()
    pack=root/'data/packs/prologue-exploration-v112.storypack'
    owned=set();first=set()
    if pack.exists():
        from astralogue.storypack import StoryPack
        with StoryPack(pack) as p:
            arc=next(iter(p.metadata['story_arcs'].values()))
            for i,t in enumerate(arc['plan']['tasks']):
                owned.update(t['main_ids'])
                if i==0:first.update(t['main_ids'])
    for path in source_files(root):
        logical=path.relative_to(root).as_posix();kind=kind_for(path);sha=file_hash(path);sid=digest([logical,sha])
        prior=store.db.execute('SELECT status FROM sources WHERE id=?',(sid,)).fetchone()
        if prior and prior[0]=='complete':continue
        scope='first_task' if any('/'+m+'/' in '/'+logical for m in first) else 'prologue' if any('/'+m+'/' in '/'+logical for m in owned) else 'global'
        count=0
        store.db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?)',(sid,logical,sha,kind,0,'scanning',None));store.db.commit()
        try:
            if path.suffix in {'.storypack','.sqlite'}:
                con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
                try:
                    arc_scopes={}
                    if kind=='storypack':
                        meta_row=con.execute("SELECT value FROM metadata WHERE key='story_arcs'").fetchone()
                        if meta_row:
                            for mission,arc in json.loads(meta_row[0]).items():
                                if str(arc.get('plan',{}).get('chapter_id'))=='100001':arc_scopes[mission]=arc['plan']['tasks']
                    tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") if not r[0].startswith('sqlite_')]
                    for table in tables:
                        quoted='"'+table.replace('"','""')+'"';batch=[];start=0
                        pk=sorted((r[5],r[1]) for r in con.execute('PRAGMA table_info('+quoted+')') if r[5])
                        order=','.join('"'+k.replace('"','""')+'"' for _,k in pk) if pk else 'rowid'
                        for offset,row in enumerate(con.execute('SELECT * FROM '+quoted+' ORDER BY '+order)):
                            raw={k:({'binary_sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} if isinstance(v,bytes) else v) for k,v in dict(row).items()}
                            for key in ['data','record','condition']:
                                if isinstance(raw.get(key),str):
                                    try:raw[key]=json.loads(raw[key])
                                    except ValueError:pass
                            text=canonical(raw);batch.append(text);count+=1
                            if kind=='native_resource_index':
                                if len(batch)>=2048:
                                    store.db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?)',(sid,table,start,offset,len(batch),digest(batch)));store.db.commit();batch=[];start=offset+1
                                continue
                            rk='execution_instance' if kind=='storypack' and table=='nodes' else 'archive_instance' if kind=='archive' and table=='occurrences' else kind+':'+table
                            rs=scope
                            data=raw.get('data',{})
                            if kind=='storypack' and table=='nodes' and raw.get('mission') in arc_scopes and isinstance(data,dict) and isinstance(data.get('task'),int):
                                tasks=arc_scopes[raw['mission']];number=data['task']
                                if 0<=number<len(tasks):rs='first_task' if tasks[number]['title']=='混乱行至深处' else 'prologue'
                            store.record(rk,str(raw.get('id',digest(raw))),raw,sid,table+':'+str(raw.get('id',offset)),rs)
                            if count%2000==0:store.db.commit()
                            batch=[]
                        if batch:store.db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?)',(sid,table,start,start+len(batch)-1,len(batch),digest(batch)))
                finally:con.close()
            else:
                obj=load_json(path)
                # Logical source hash + JSON pointer deduplicates identical upstream copies.
                if kind in {'dialogue_catalog','textmap_only'}:
                    entries=enumerate(obj) if isinstance(obj,list) else obj.items()
                elif isinstance(obj,dict) and 'story' in obj:
                    entries=enumerate(obj['story']);scope='first_task' if obj.get('title')=='混乱行至深处' else 'prologue' if obj.get('title') in {'漩涡止于中心','宇宙安宁片刻','阴影从未离去','模拟宇宙•始发测试','旅途正在继续','星间流浪'} else scope
                elif kind=='ir_representation':
                    entries=[]
                    for component,value in obj.items():
                        if isinstance(value,list):entries.extend((component+'/'+str(i),{'component':component,'value':v}) for i,v in enumerate(value))
                        elif isinstance(value,dict) and component=='texts':entries.extend((component+'/'+str(k),{'component':component,'value':v}) for k,v in value.items())
                        else:entries.append((component,{'component':component,'value':value}))
                elif isinstance(obj,list):entries=enumerate(obj)
                else:entries=[('',obj)]
                for key,value in entries:
                    store.record(kind,sha+':/'+str(key),value,sid,'/'+str(key),scope);count+=1
                    if count%2000==0:store.db.commit()
            store.db.execute('UPDATE sources SET rows=?,status=? WHERE id=?',(count,'complete',sid));store.db.commit()
        except Exception as e:
            store.db.execute('UPDATE sources SET rows=?,status=?,error=? WHERE id=?',(count,'failed',type(e).__name__+': '+str(e)[:500],sid));store.db.commit()
    store.setting('root',str(root));return store.report()
