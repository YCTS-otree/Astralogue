"""Reversible human decisions and cancellation of an entire research lineage."""
import json
import time
from astralogue.model import canonical


def lineage(store,pid):
    children={};jobs={}
    for row in store.db.execute("SELECT id,context FROM jobs WHERE scope LIKE 'human_feedback:%'"):
        parent=json.loads(row['context']).get('parent_proposal')
        if parent:jobs.setdefault(parent,set()).add(row['id'])
    for row in store.db.execute('SELECT id,payload FROM proposals'):
        parent=json.loads(row['payload'])['context'].get('parent_proposal')
        if parent:children.setdefault(parent,set()).add(row['id'])
    pending=[pid];seen=set();all_jobs=set()
    while pending:
        current=pending.pop()
        if current in seen:continue
        seen.add(current);all_jobs.update(jobs.get(current,set()));pending.extend(children.get(current,set()))
    return seen,all_jobs


def undo(store,pid,action,reviewer):
    if action not in {'undo_reject','undo_research'} or not reviewer.strip():raise ValueError('请填写审核人并选择撤销操作')
    store.db.execute('BEGIN IMMEDIATE')
    try:
        row=store.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('未找到申请')
        ids={pid};jobs=set()
        if action=='undo_reject':
            if row['status']!='rejected':raise ValueError('该申请并非已驳回，不能重复撤销')
        else:
            if not store.db.execute("SELECT 1 FROM review_comments c JOIN jobs j ON j.id=c.job WHERE c.proposal=? AND c.action='research_approve' AND j.status!='cancelled'",(pid,)).fetchone():raise ValueError('没有可撤销的研究批准')
            ids,jobs=lineage(store,pid)
            path=store.setting('publication_pack')
            if path:
                from .publication import rollback_research
                rolled=rollback_research(path,ids)
                for proposal in rolled:
                    store.db.execute("UPDATE publications SET status='rolled_back',result=? WHERE proposal=?",(canonical({'status':'rolled_back','error':'所属研究已撤销'}),proposal))
        for proposal in ids:
            item=store.db.execute('SELECT payload,status FROM proposals WHERE id=?',(proposal,)).fetchone()
            status='pending' if proposal==pid else 'withdrawn'
            store.db.execute('UPDATE proposals SET status=?,reviewer=?,reviewed_at=? WHERE id=?',(status,reviewer,time.time(),proposal))
            store.db.execute('INSERT INTO review_log(proposal,action,reviewer,at,before,after) VALUES(?,?,?,?,?,?)',
                (proposal,action if proposal==pid else 'withdraw_with_research',reviewer,time.time(),canonical({'status':item['status'],'payload':json.loads(item['payload'])}),canonical({'status':status,'root':pid})))
        for jid in jobs:store.db.execute("UPDATE jobs SET status='cancelled',error='人工撤销所属研究；不再生成申请' WHERE id=?",(jid,))
        store.db.commit()
        return {'withdrawn':len(ids)-1,'cancelled_jobs':len(jobs)}
    except Exception:store.db.rollback();raise
