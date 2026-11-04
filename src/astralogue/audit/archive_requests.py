"""Time-bounded removal from review lists, with retained audit history."""
import time
from astralogue.model import canonical
from .pages import ordered


def archive_research(store,cutoff,bounds=None):
    bounds=bounds or {};removed=[];unknown=[];cancelled=[]
    store.db.execute('BEGIN IMMEDIATE')
    try:
        for item in ordered(store):
            if item['ready']:continue
            row=item['row'];created=row['created_at'];bound=bounds.get(row['id'])
            upper=created if created is not None else bound.get('submitted_before') if bound else None
            if upper is None:unknown.append(row['id']);continue
            if upper>cutoff:continue
            now=time.time();store.db.execute('UPDATE proposals SET deleted_at=? WHERE id=?',(now,row['id']))
            store.db.execute('INSERT INTO review_log(proposal,action,reviewer,at,before,after) VALUES(?,?,?,?,?,?)',
                (row['id'],'delete_research_before_cutoff','用户授权时间范围清理',now,canonical({'status':row['status'],'deleted_at':None}),
                 canonical({'deleted_at':now,'cutoff':cutoff,'created_at':created,'legacy_upper_bound':bound})))
            removed.append(row['id'])
        if removed:
            for job in store.db.execute("SELECT id,context,created_at FROM jobs WHERE scope LIKE 'human_feedback:%' AND status IN ('pending','running')").fetchall():
                import json
                if json.loads(job['context']).get('parent_proposal') not in removed:continue
                submitted=job['created_at']
                if submitted is None:submitted=store.db.execute('SELECT MIN(at) FROM review_comments WHERE job=?',(job['id'],)).fetchone()[0]
                if submitted is not None and submitted<=cutoff:
                    store.db.execute("UPDATE jobs SET status='cancelled',error='用户按提交时间删除旧研究，旧任务已取消' WHERE id=?",(job['id'],));cancelled.append(job['id'])
        store.db.commit()
        return {'removed':removed,'unknown_time_kept':unknown,'cancelled_old_jobs':cancelled,'cutoff':cutoff}
    except Exception:store.db.rollback();raise
