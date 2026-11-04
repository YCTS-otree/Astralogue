import sqlite3,time,json
from astralogue.audit.store import AuditStore
from astralogue.audit.pages import ordered,detail_page
from astralogue.audit.archive_requests import archive_research
from astralogue.model import canonical
from test_audit_webui import seed


def test_old_schema_keeps_unknown_times_but_new_insert_records_time(tmp_path):
    path=tmp_path/'old.sqlite';con=sqlite3.connect(path)
    con.execute('CREATE TABLE proposals(id TEXT PRIMARY KEY,job TEXT,payload TEXT,status TEXT DEFAULT \'pending\',reviewer TEXT,reviewed_at REAL)')
    con.execute('INSERT INTO proposals(id,payload) VALUES(?,?)',('legacy','{}'));con.commit();con.close()
    with AuditStore(path) as s:
        assert s.db.execute("SELECT created_at FROM proposals WHERE id='legacy'").fetchone()[0] is None
        before=time.time();s.db.execute("INSERT INTO proposals(id,payload) VALUES('new','{}')");s.db.commit()
        created=s.db.execute("SELECT created_at FROM proposals WHERE id='new'").fetchone()[0]
        assert before-1<=created<=time.time()+1


def test_cutoff_only_removes_old_research_not_concrete_or_new(tmp_path):
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        s.db.execute("UPDATE proposals SET created_at=100 WHERE id IN ('earlier','research')")
        p=s.db.execute("SELECT payload FROM proposals WHERE id='research'").fetchone()[0]
        s.db.execute("INSERT INTO proposals(id,payload,created_at) VALUES('new-research',?,300)",(p,));s.db.commit()
        result=archive_research(s,200)
        assert result['removed']==['research']
        ids={r['row']['id'] for r in ordered(s)}
        assert 'earlier' in ids and 'new-research' in ids and 'research' not in ids
        assert '已从列表删除' in detail_page(s,'research','token','human')
        assert s.db.execute("SELECT COUNT(*) FROM review_log WHERE action='delete_research_before_cutoff'").fetchone()[0]==1


def test_unknown_legacy_time_requires_explicit_bound(tmp_path):
    path=tmp_path/'a.sqlite';seed(path)
    with AuditStore(path) as s:
        s.db.execute("UPDATE proposals SET created_at=NULL WHERE id='research'");s.db.commit()
        assert archive_research(s,200)['unknown_time_kept']==['research']
        result=archive_research(s,200,{'research':{'submitted_before':150,'evidence':'fixed earlier snapshot'}})
        assert result['removed']==['research']
