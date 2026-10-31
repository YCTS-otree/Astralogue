"""Offline evidence archive. Display order never implies execution order."""
import json
import sqlite3
from pathlib import Path
from astralogue.model import canonical, digest, file_hash, load_json
from astralogue.storypack import StoryPack

DDL='''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE missions(id TEXT PRIMARY KEY,record TEXT);
CREATE TABLE texts(id TEXT PRIMARY KEY,hash TEXT,lang TEXT,text TEXT,speaker TEXT);
CREATE TABLE catalog_records(id TEXT PRIMARY KEY,record TEXT);
CREATE TABLE occurrences(id TEXT PRIMARY KEY,text_id TEXT,mission TEXT,node TEXT,group_id TEXT,evidence TEXT,kind TEXT);
CREATE TABLE occurrence_sources(id TEXT PRIMARY KEY,occurrence TEXT,record TEXT);
CREATE TABLE relations(id TEXT PRIMARY KEY,source TEXT,target TEXT,verified INTEGER,record TEXT);
CREATE INDEX occurrences_text ON occurrences(text_id);
CREATE INDEX occurrences_mission ON occurrences(mission);
'''

def build(source, packs, output, force=False):
    if output.exists() and not force: raise ValueError('档案已存在，需 --force')
    from astralogue.hsr.manifest import create_manifest
    manifest=create_manifest(source); tm=load_json(source/'TextMap/TextMapCHS.json')
    rows=load_json(source/'ExcelOutput/TalkSentenceConfig.json')
    temp=output.with_suffix('.building'); output.parent.mkdir(parents=True,exist_ok=True)
    temp.unlink(missing_ok=True)
    con=sqlite3.connect(temp); con.executescript(DDL)
    inputs={}; version=manifest['source']; missions=manifest['missions']
    def occurrence(tid,mission,node,group,evidence,kind):
        oid=digest([tid,mission,node,group,evidence.get("sha256") if kind=="raw_reference" else evidence.get("data")])
        con.execute("INSERT OR IGNORE INTO occurrence_sources VALUES(?,?,?)",(digest([oid,evidence]),oid,canonical(evidence)))
        con.execute('INSERT OR IGNORE INTO occurrences VALUES(?,?,?,?,?,?,?)',(oid,tid,mission,node,group,canonical(evidence),kind))
    for m in missions: con.execute('INSERT INTO missions VALUES(?,?)',(m['id'],canonical(m)))
    for row in rows:
        sid=row.get('TalkSentenceID'); h=row.get('TalkSentenceText',{}).get('Hash')
        if sid is None or h is None: continue
        name=row.get('TextmapTalkSentenceName',{}).get('Hash')
        con.execute('INSERT OR IGNORE INTO catalog_records VALUES(?,?)',(str(sid),canonical(row)))
        con.execute('INSERT OR IGNORE INTO texts VALUES(?,?,?,?,?)',(str(sid),str(h),'CHS',tm.get(str(h)),tm.get(str(name))))
    # Explicit submission resources only. Directory matches remain candidates.
    ownership={}
    for m in missions:
        for s in m['submissions']:
            if s.get('resource'): ownership.setdefault(s['resource'],set()).add(m['id'])
    def walk(obj,pointer=''):
        if isinstance(obj,dict):
            if 'TalkSentenceID' in obj: yield str(obj['TalkSentenceID']),pointer,obj
            for k,v in obj.items(): yield from walk(v,pointer+'/'+str(k))
        elif isinstance(obj,list):
            for i,v in enumerate(obj): yield from walk(v,pointer+'/'+str(i))
    for folder in ['Story','Config/Level/Mission']:
        for p in sorted((source/folder).rglob('*.json')):
            logical=p.relative_to(source).as_posix(); sha=file_hash(p); inputs[logical]=sha
            for tid,ptr,obj in walk(load_json(p)):
                for mid in ownership.get(logical,{None}):
                    occurrence(tid,mid,logical+ptr,logical,{'file':logical,'pointer':ptr,'sha256':sha,'raw':obj,'ownership':'explicit_submission' if mid else 'unknown'},'raw_reference')
    for pack in packs:
        with StoryPack(pack) as sp:
            b=sp.bundle()
            upstream=b.metadata.get('source',{})
            if upstream.get('revision') and upstream.get('revision')!=version.get('revision'): raise ValueError('Archive source revision conflict')
            info=b.metadata.get('narrative',{}); inputs['pack:'+sp.metadata['pack_id']]=file_hash(pack)
            for n in b.nodes:
                sid=n.data.get('talk_sentence_id')
                if sid is None: continue
                # Same source sentence is one text, each graph placement remains an instance.
                tid=str(sid)
                owner=next((m.original_id for m in b.missions if m.id==n.mission and m.original_id in {x["id"] for x in missions}),None)
                occurrence(tid,owner,n.id,n.mission,{'pack_id':sp.metadata['pack_id'],'node':n.id,'data':n.data,'mode':info.get('modes',{}).get(n.mission,{}),'text':b.texts.get(n.text)},'graph_instance')
            for e in b.edges:
                rel=info.get('relations',{}).get(e.id)
                verified=bool(rel and rel.get('verified'))
                con.execute('INSERT OR IGNORE INTO relations VALUES(?,?,?,?,?)',(digest([e.__dict__,rel]),e.source,e.target,int(verified),canonical({'pack':str(pack),'pack_id':sp.metadata['pack_id'],'edge':e.__dict__,'evidence':rel})))
    for p in [source/'ExcelOutput/TalkSentenceConfig.json',source/'TextMap/TextMapCHS.json',source/'ExcelOutput/MainMission.json',source/'ExcelOutput/MissionChapterConfig.json']:
        inputs[p.relative_to(source).as_posix()]=file_hash(p)
    for key,value in {'archive_schema':1,'source':version,'inputs':inputs,'manifest':manifest['denominator'],'scope':'local snapshot, not complete game','textmap_strings':len(tm)}.items():
        con.execute('INSERT INTO metadata VALUES(?,?)',(key,canonical(value)))
    con.commit();con.close();temp.replace(output)
    with Archive(output) as a:return a.coverage()

class Archive:
    def __init__(self,path):
        self.con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);self.con.row_factory=sqlite3.Row
        self.meta={r['key']:json.loads(r['value']) for r in self.con.execute('SELECT * FROM metadata')}
    def __enter__(self):return self
    def __exit__(self,*args):self.con.close()
    def search(self,search='',mission=None,chapter=None,speaker=None,orphans=False,offset=0,limit=20,category=None):
        # instr is an exact Unicode substring search: no unsupported Chinese tokenizer assumptions.
        query='SELECT DISTINCT t.* FROM texts t LEFT JOIN occurrences o ON o.text_id=t.id LEFT JOIN missions m ON m.id=o.mission WHERE t.text IS NOT NULL'
        args=[]
        for sql,value in [('(instr(t.text,?)>0 OR t.id=?)',search),('o.mission=?',mission),("instr(json_extract(m.record,'$.chapter_title'),?)>0",chapter),('instr(t.speaker,?)>0',speaker)]:
            if value:
                query+=' AND '+sql;args.extend([value,value] if value==search and sql.startswith('(') else [value])
        if category:
            query+=" AND json_extract(m.record,'$.category')=?";args.append(category)
        if orphans:query+=' AND NOT EXISTS(SELECT 1 FROM occurrences x JOIN relations r ON (r.source=x.node OR r.target=x.node) AND r.verified=1 WHERE x.text_id=t.id)'
        query+=' ORDER BY t.id LIMIT ? OFFSET ?';args.extend([limit,offset])
        return [dict(r) for r in self.con.execute(query,args)]
    def detail(self,tid):
        text=self.con.execute('SELECT * FROM texts WHERE id=?',(tid,)).fetchone()
        occ=[dict(r) for r in self.con.execute('SELECT * FROM occurrences WHERE text_id=?',(tid,))]
        for o in occ:o['evidence']=json.loads(o['evidence'])
        nodes={o['node'] for o in occ}
        relations=[dict(r) for r in self.con.execute('SELECT * FROM relations') if r['source'] in nodes or r['target'] in nodes]
        raw=self.con.execute('SELECT record FROM catalog_records WHERE id=?',(tid,)).fetchone()
        return {'catalog_record':json.loads(raw[0]) if raw else None,'catalog_source':{'file':'ExcelOutput/TalkSentenceConfig.json','source':self.meta['source']},'text':dict(text) if text else None,'occurrences':occ,'relations':relations,'knowledge_type':'character_statement_not_verified_world_fact'}
    def tasks(self):
        result=[]
        for o in self.con.execute('SELECT * FROM occurrences WHERE kind="graph_instance"'):
            edges=list(self.con.execute('SELECT * FROM relations WHERE source=? AND verified=1',(o['node'],)))
            if edges:continue
            candidates=[dict(r) for r in self.con.execute('SELECT * FROM relations WHERE source=?',(o['node'],))]
            result.append({'id':digest([o['id'],self.meta['inputs']]),'task_type':'unresolved_transition','source_node':o['node'],'mission_id':o['group_id'],'candidate_targets':candidates,'status':'needs_review','inputs':self.meta['inputs'],'source':self.meta['source'],'evidence':json.loads(o['evidence'])})
        return result
    def coverage(self):
        count=lambda q:self.con.execute(q).fetchone()[0]
        return {'scope':self.meta['scope'],'sentence_ids':count('SELECT count(*) FROM texts'),'available_texts':count('SELECT count(*) FROM texts WHERE text IS NOT NULL'),'referenced_sentence_ids':count('SELECT count(DISTINCT text_id) FROM occurrences WHERE text_id IN (SELECT id FROM texts)'),'mission_assigned':count('SELECT count(DISTINCT text_id) FROM occurrences WHERE mission IS NOT NULL AND text_id IN (SELECT id FROM texts)'),'graph_instances':count('SELECT count(*) FROM occurrences WHERE kind="graph_instance"'),'verified_relations':count('SELECT count(*) FROM relations WHERE verified=1'),'review_tasks':len(self.tasks()),'textmap_strings_not_assumed_dialogue':self.meta['textmap_strings'],'trailblaze_assigned':count("SELECT count(DISTINCT o.text_id) FROM occurrences o JOIN missions m ON m.id=o.mission JOIN texts t ON t.id=o.text_id WHERE json_extract(m.record,'$.category')='TRAILBLAZE'"),'unassigned':count('SELECT count(*) FROM texts t WHERE NOT EXISTS(SELECT 1 FROM occurrences o WHERE o.text_id=t.id AND o.mission IS NOT NULL)'),'full_missions_proven':0}
