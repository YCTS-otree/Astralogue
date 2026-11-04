"""Persistent audit evidence, jobs, costs and human review. No pack writes."""
from pathlib import Path
import json
import sqlite3
import time
from astralogue.model import canonical,digest

DDL='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,path TEXT,sha256 TEXT,kind TEXT,rows INTEGER,status TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT,logical TEXT,scope TEXT,payload TEXT);
CREATE INDEX IF NOT EXISTS records_scope ON records(scope,kind);
CREATE TABLE IF NOT EXISTS origins(record TEXT,source TEXT,locator TEXT,PRIMARY KEY(record,source,locator));
CREATE INDEX IF NOT EXISTS origins_source ON origins(source,record);
CREATE TABLE IF NOT EXISTS receipts(source TEXT,table_name TEXT,start_row INTEGER,end_row INTEGER,count INTEGER,sha256 TEXT,PRIMARY KEY(source,table_name,start_row));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,pass INTEGER,scope TEXT,context TEXT,deps TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,error TEXT,result TEXT,cache_key TEXT);
CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,job TEXT,provider TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,seconds REAL,cost REAL,cache_hit INTEGER,error TEXT,metadata TEXT);
CREATE INDEX IF NOT EXISTS calls_job ON calls(job,id);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,job TEXT,payload TEXT,status TEXT DEFAULT 'pending',reviewer TEXT,reviewed_at REAL);
CREATE TABLE IF NOT EXISTS review_log(id INTEGER PRIMARY KEY,proposal TEXT,action TEXT,reviewer TEXT,at REAL,before TEXT,after TEXT);
CREATE TABLE IF NOT EXISTS review_comments(id INTEGER PRIMARY KEY,proposal TEXT,reviewer TEXT,comment TEXT,action TEXT,job TEXT,at REAL);
CREATE TABLE IF NOT EXISTS publications(proposal TEXT PRIMARY KEY,status TEXT,result TEXT,at REAL);
CREATE TABLE IF NOT EXISTS proposal_links(job TEXT,proposal TEXT,reason TEXT,PRIMARY KEY(job,proposal));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
'''

class AuditStore:
    def __init__(self,path=Path('data/audit/audit.sqlite')):
        self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30);self.db.row_factory=sqlite3.Row
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0,1}:self.db.close();raise ValueError('Unsupported narrative audit schema')
        self.db.executescript(DDL);self.db.execute('PRAGMA user_version=1')
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            for table,fields in [('proposals',{'created_at':'REAL','deleted_at':'REAL'}),('jobs',{'created_at':'REAL'})]:
                columns={r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}
                for name,typ in fields.items():
                    if name not in columns:self.db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+typ)
                self.db.execute("CREATE TRIGGER IF NOT EXISTS "+table+"_submitted_at AFTER INSERT ON "+table+" WHEN NEW.created_at IS NULL BEGIN UPDATE "+table+" SET created_at=(julianday('now')-2440587.5)*86400.0 WHERE id=NEW.id; END")

    def close(self):self.db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def setting(self,key,value=None):
        if value is not None:
            with self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,canonical(value)))
        row=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def record(self,kind,logical,payload,source,locator,scope='global'):
        rid=digest([kind,logical,payload])
        self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?)',(rid,kind,logical,scope,canonical(payload)))
        if scope!='global':self.db.execute("UPDATE records SET scope=? WHERE id=? AND scope='global'",(scope,rid))
        self.db.execute('INSERT OR IGNORE INTO origins VALUES(?,?,?)',(rid,source,locator));return rid
    def job(self,pass_,scope,context,deps=()):
        jid=digest(['audit-v1',pass_,scope,context,list(deps)])
        self.db.execute('INSERT OR IGNORE INTO jobs(id,pass,scope,context,deps) VALUES(?,?,?,?,?)',(jid,pass_,scope,canonical(context),canonical(list(deps))))
        return jid
    def report(self):
        def groups(table,col):
            where=' WHERE deleted_at IS NULL' if table=='proposals' else ''
            return dict(self.db.execute(f'SELECT {col},COUNT(*) FROM {table}{where} GROUP BY {col}'))
        calls=self.db.execute('SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(cost),0),COALESCE(SUM(seconds),0) FROM calls').fetchone()
        return {'sources':groups('sources','status'),'records_by_kind':groups('records','kind'),'records_by_scope':groups('records','scope'),
            'source_rows_traversed':self.db.execute('SELECT COALESCE(SUM(rows),0) FROM sources').fetchone()[0],
            'receipt_rows':self.db.execute('SELECT COALESCE(SUM(count),0) FROM receipts').fetchone()[0],
            'jobs':groups('jobs','status'),'proposals':groups('proposals','status'),'archived_proposals':self.db.execute('SELECT COUNT(*) FROM proposals WHERE deleted_at IS NOT NULL').fetchone()[0],'tokens_in':calls[0],'tokens_out':calls[1],
            'api_cost':calls[2],'inference_seconds':calls[3],
            'llm_reviewed_jobs_by_scope':dict(self.db.execute("SELECT scope,COUNT(*) FROM jobs WHERE status='done' GROUP BY scope")),
            'human_review_is_not_game_verification':True}
