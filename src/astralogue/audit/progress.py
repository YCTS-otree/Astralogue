"""Parent review progress follows the latest submitted revision job."""

def refresh(store):
    with store.db:
        for row in store.db.execute("SELECT id,status FROM proposals WHERE deleted_at IS NULL AND status IN ('awaiting_revision','revision_submitted','revision_failed')").fetchall():
            job=store.db.execute('SELECT j.id,j.status FROM review_comments c JOIN jobs j ON j.id=c.job WHERE c.proposal=? ORDER BY c.id DESC LIMIT 1',(row['id'],)).fetchone()
            if not job:continue
            if job['status'] in {'pending','running'}:state='awaiting_revision'
            elif job['status']=='failed':state='revision_failed'
            elif job['status']=='done':
                children=store.db.execute("SELECT 1 FROM proposals WHERE (job=? OR id IN (SELECT proposal FROM proposal_links WHERE job=?)) AND deleted_at IS NULL AND status NOT IN ('withdrawn','invalid_revision','superseded') LIMIT 1",(job['id'],job['id'])).fetchone()
                state='revision_submitted' if children else 'revision_failed'
            else:continue
            if row['status']!=state:store.db.execute('UPDATE proposals SET status=? WHERE id=?',(state,row['id']))
