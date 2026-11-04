"""Transactional in-place Reader revisions, with compressed changed-row history."""
from pathlib import Path
import json
import sqlite3
import time
import zlib
from astralogue.model import canonical,digest
from astralogue.storypack import StoryPack
from astralogue.validation import validate
from .cleanup import compile_cleanup

KEYS={'metadata':['key'],'nodes':['id'],'edges':['id'],'texts':['id','lang']}


def snapshot(con):
    return {table:{tuple(r[k] for k in keys):dict(r) for r in con.execute('SELECT * FROM '+table)} for table,keys in KEYS.items()}


def desired(bundle,old):
    result={k:dict(v) for k,v in old.items()}
    result['metadata']={(k,):{'key':k,'value':canonical(v)} for k,v in bundle.metadata.items()}
    result['nodes']={(n.id,):{**n.__dict__,'data':canonical(n.data)} for n in bundle.nodes}
    result['edges']={(e.id,):{**e.__dict__,'condition':canonical(e.condition) if e.condition is not None else None} for e in bundle.edges}
    result['texts']={(tid,lang):{'id':tid,'lang':lang,'value':text} for tid,langs in bundle.texts.items() for lang,text in langs.items()}
    return result


def changes(old,new):
    return [{'table':table,'key':list(key),'before':old[table].get(key),'after':new[table].get(key)}
            for table in KEYS for key in sorted(set(old[table])|set(new[table])) if old[table].get(key)!=new[table].get(key)]


def json_diff(before,after,path=()):
    if isinstance(before,dict) and isinstance(after,dict):
        result=[]
        for key in sorted(set(before)|set(after)):
            if key in before and key in after:result+=json_diff(before[key],after[key],path+(key,))
            else:result.append({'path':list(path+(key,)),'before_exists':key in before,'before':before.get(key),'after_exists':key in after,'after':after.get(key)})
        return result
    return [] if before==after else [{'path':list(path),'before_exists':True,'before':before,'after_exists':True,'after':after}]


def compact(delta):
    result=[]
    for change in delta:
        if change['table']=='metadata' and change.get('before') and change.get('after'):
            before=json.loads(change['before']['value']);after=json.loads(change['after']['value'])
            result.append({'table':'metadata','key':change['key'],'json_delta':json_diff(before,after)})
        else:result.append(change)
    return result


def patched_json(value,edits,reverse):
    from copy import deepcopy
    value=deepcopy(value)
    for edit in edits:
        old='after' if reverse else 'before';new='before' if reverse else 'after'
        if not edit['path']:
            if value!=edit[old]:raise ValueError('历史元数据已变化')
            value=deepcopy(edit[new]);continue
        parent=value
        for key in edit['path'][:-1]:parent=parent[key]
        key=edit['path'][-1]
        if (key in parent)!=edit[old+'_exists'] or (key in parent and parent[key]!=edit[old]):raise ValueError('历史字段已变化')
        if edit[new+'_exists']:parent[key]=deepcopy(edit[new])
        else:del parent[key]
    return value


def compact_history(path):
    con=connection(path)
    try:
        with con:
            for row in con.execute('SELECT revision,delta,sha256 FROM reader_revisions').fetchall():
                old=json.loads(zlib.decompress(row['delta']))
                if digest(old)!=row['sha256']:raise ValueError('历史校验失败')
                if any('json_delta' in c for c in old):continue
                new=compact(old)
                con.execute('UPDATE reader_revisions SET delta=?,sha256=? WHERE revision=?',(zlib.compress(canonical(new).encode()),digest(new),row['revision']))
    finally:con.close()


def apply_rows(con,delta,reverse=False):
    for change in delta:
        table=change['table'];keys=KEYS[table];where=' AND '.join(k+'=?' for k in keys)
        if 'json_delta' in change:
            row=con.execute('SELECT value FROM metadata WHERE key=?',change['key']).fetchone()
            if row is None:raise ValueError('历史元数据缺失')
            value=patched_json(json.loads(row['value']),change['json_delta'],reverse)
            con.execute('UPDATE metadata SET value=? WHERE key=?',(canonical(value),change['key'][0]));continue
        expected=change['after' if reverse else 'before'];replacement=change['before' if reverse else 'after']
        row=con.execute('SELECT * FROM '+table+' WHERE '+where,change['key']).fetchone()
        if (dict(row) if row else None)!=expected:raise ValueError('修订行已变化，拒绝覆盖：'+table)
        if replacement is None:con.execute('DELETE FROM '+table+' WHERE '+where,change['key'])
        else:
            cols=list(replacement)
            con.execute('INSERT OR REPLACE INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',list(replacement.values()))


def connection(path):
    con=sqlite3.connect(Path(path),timeout=30);con.row_factory=sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS reader_revisions(revision INTEGER PRIMARY KEY,proposal TEXT,at REAL,delta BLOB,sha256 TEXT,rolled_back INTEGER DEFAULT 0)')
    con.commit();return con


def publish(path,proposal,patch):
    con=connection(path)
    try:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM reader_revisions WHERE proposal=? AND rolled_back=0',(proposal,)).fetchone():
            con.rollback();return {'status':'already_published','proposal':proposal}
        old=snapshot(con)
        with StoryPack(Path(path)) as pack:base=pack.bundle()
        # A second approval cannot silently move the same body again.
        prior=base.metadata.get('audit_cleanup',{}).get('published_nodes',[])
        selected={n for op in patch['operations'] for n in op.get('nodes',[])}
        if selected.intersection(prior):raise ValueError('修订节点与已发布修改重叠，需要合并审核')
        result=compile_cleanup(base,[patch])
        if result.metadata['audit_cleanup']['deferred']:raise ValueError('此操作尚无可发布的明确执行计划')
        before_errors={canonical(d) for d in validate(base)['diagnostics'] if d['severity']=='error'}
        after_errors={canonical(d) for d in validate(result)['diagnostics'] if d['severity']=='error'}
        if after_errors-before_errors:raise ValueError('发布引入新的验证错误')
        if not {n.id for n in base.nodes}.issubset({n.id for n in result.nodes}):raise ValueError('实时修订不能删除既有节点')
        rev=con.execute('SELECT COALESCE(MAX(revision),0)+1 FROM reader_revisions').fetchone()[0]
        # pack_id is the immutable base identity. The explicit capability and
        # live_revision identify this compatible update contract to readers.
        for key in ['pack_id','pack_version','schema_version','version']:
            if key in base.metadata:result.metadata[key]=base.metadata[key]
        result.metadata['required_capabilities']=sorted(set(base.metadata.get('required_capabilities',[]))|{'live-reader-revisions-v1'})
        result.metadata['live_revision']={'number':rev,'base_pack_id':base.metadata['pack_id'],'proposal':proposal}
        result.metadata['audit_cleanup']['published_nodes']=sorted(set(prior)|selected)
        delta=changes(old,desired(result,old));history=compact(delta);raw=canonical(history).encode()
        apply_rows(con,delta)
        con.execute('INSERT INTO reader_revisions(revision,proposal,at,delta,sha256) VALUES(?,?,?,?,?)',(rev,proposal,time.time(),zlib.compress(raw),digest(history)))
        con.commit();con.execute('PRAGMA wal_checkpoint(PASSIVE)')
        return {'status':'published','revision':rev,'changed_rows':len(delta),'history_bytes':len(zlib.compress(raw)),'proposal':proposal}
    except Exception:con.rollback();raise
    finally:con.close()


def rollback(path):
    con=connection(path)
    try:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM reader_revisions WHERE rolled_back=0 ORDER BY revision DESC LIMIT 1').fetchone()
        if not row:raise ValueError('没有可回滚的修订')
        delta=json.loads(zlib.decompress(row['delta']))
        if digest(delta)!=row['sha256']:raise ValueError('历史校验失败')
        apply_rows(con,list(reversed(delta)),True)
        con.execute('UPDATE reader_revisions SET rolled_back=1 WHERE revision=?',(row['revision'],));con.commit()
        con.execute('PRAGMA wal_checkpoint(PASSIVE)')
        return row['revision']
    except Exception:con.rollback();raise
    finally:con.close()


def publish_approved(store,ids):
    from .review import export_patch
    path=store.setting('publication_pack')
    if not path:return []
    outcomes=[]
    for pid in ids:
        try:
            with StoryPack(Path(path)) as pack:
                has_history=pack.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reader_revisions'").fetchone()
                active=pack.con.execute('SELECT revision FROM reader_revisions WHERE proposal=? AND rolled_back=0',(pid,)).fetchone() if has_history else None
                if not active:patch=export_patch(store,pid,pack.bundle())
            result={'status':'already_published','proposal':pid,'revision':active[0]} if active else publish(Path(path),pid,patch)
        except Exception as error:
            result={'status':'failed','proposal':pid,'error':str(error)}
        with store.db:store.db.execute('INSERT OR REPLACE INTO publications VALUES(?,?,?,?)',(pid,result['status'],canonical(result),time.time()))
        outcomes.append(result)
    return outcomes

def rollback_research(path,proposals):
    """Revert only a contiguous suffix owned by this research, atomically."""
    con=connection(path)
    try:
        con.execute('BEGIN IMMEDIATE')
        active=con.execute('SELECT * FROM reader_revisions WHERE rolled_back=0 ORDER BY revision DESC').fetchall()
        selected=[r for r in active if r['proposal'] in proposals]
        if not selected:con.rollback();return []
        cutoff=min(r['revision'] for r in selected)
        suffix=[r for r in active if r['revision']>=cutoff]
        if any(r['proposal'] not in proposals for r in suffix):raise ValueError('后续已有其他研究的已发布修订；请先按历史顺序回滚，整次研究撤销未执行。')
        for row in suffix:
            delta=json.loads(zlib.decompress(row['delta']))
            if digest(delta)!=row['sha256']:raise ValueError('发布历史校验失败，撤销未执行')
            apply_rows(con,list(reversed(delta)),True)
            con.execute('UPDATE reader_revisions SET rolled_back=1 WHERE revision=?',(row['revision'],))
        con.commit();con.execute('PRAGMA wal_checkpoint(PASSIVE)')
        return [r['proposal'] for r in suffix]
    except Exception:con.rollback();raise
    finally:con.close()
