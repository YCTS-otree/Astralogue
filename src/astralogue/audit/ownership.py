"""Whole-index reference integrity and explicit multi-candidate ownership evidence."""
import json
from astralogue.model import canonical


def references(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in {'TalkSentenceID','talk_sentence_id','sentence_id'} and isinstance(v,(int,str)):yield str(v)
            elif k in {'sentence_ids','talk_sentence_ids'} and isinstance(v,list):
                yield from (str(x) for x in v if isinstance(x,(int,str)))
            else:yield from references(v)
    elif isinstance(value,list):
        for v in value:yield from references(v)


def check(store):
    store.db.executescript('''CREATE TABLE IF NOT EXISTS dialogue_refs(record TEXT,sentence TEXT,scope TEXT,valid INTEGER,PRIMARY KEY(record,sentence));
    CREATE TABLE IF NOT EXISTS ownership_candidates(sentence TEXT,scope TEXT,evidence_record TEXT,PRIMARY KEY(sentence,scope,evidence_record));''')
    catalog={}
    for row in store.db.execute("SELECT id,payload FROM records WHERE kind='dialogue_catalog'"):
        value=json.loads(row['payload']);sid=value.get('TalkSentenceID')
        if sid is not None:catalog.setdefault(str(sid),[]).append(row['id'])
    # Use a separate read connection to avoid cursor/write snapshot upgrades.
    import sqlite3
    reader=sqlite3.connect(store.path);reader.row_factory=sqlite3.Row
    try:
        for count,row in enumerate(reader.execute("SELECT id,scope,payload FROM records WHERE kind IN ('source_instance','execution_instance','ir_representation','archive_instance')")):
            for sid in set(references(json.loads(row['payload']))):
                store.db.execute('INSERT OR REPLACE INTO dialogue_refs VALUES(?,?,?,?)',(row['id'],sid,row['scope'],int(sid in catalog)))
                if row['scope']!='global':
                    store.db.execute('INSERT OR IGNORE INTO ownership_candidates VALUES(?,?,?)',(sid,row['scope'],row['id']))
            if count%1000==0:store.db.commit()
        store.db.commit()
    finally:reader.close()
    report={'unique_dialogue_ids':len(catalog),'references':store.db.execute('SELECT COUNT(*) FROM dialogue_refs').fetchone()[0],
            'invalid_reference_instances':store.db.execute('SELECT COUNT(*) FROM dialogue_refs WHERE valid=0').fetchone()[0],
            'owned_candidates':store.db.execute('SELECT COUNT(DISTINCT sentence) FROM ownership_candidates').fetchone()[0],
            'first_task_candidate_ids':store.db.execute("SELECT COUNT(DISTINCT sentence) FROM ownership_candidates WHERE scope='first_task'").fetchone()[0],
            'ownership_is_source_association_not_trigger_verification':True}
    store.setting('ownership_report',report);return report
