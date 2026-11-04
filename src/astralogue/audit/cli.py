from pathlib import Path
import json
import typer
from .store import AuditStore
app=typer.Typer(no_args_is_help=True)
DB=Path('data/audit/audit.sqlite')

@app.command('index')
def index(db:Path=DB,root:Path=Path('.')):
    from .inventory import traverse
    with AuditStore(db) as s:typer.echo(json.dumps(traverse(s,root),ensure_ascii=False))

@app.command('prepare')
def prepare_cmd(db:Path=DB,root:Path=Path('.'),pack:Path=Path('data/packs/prologue-exploration-v112.storypack'),block_size:int=8):
    from .jobs import prepare,queue_unassigned
    from .findings import discover
    root=root.resolve()
    with AuditStore(db) as s:
        plan=prepare(s,root,pack.resolve(),block_size)
        findings=discover(s,pack.resolve(),root/'data/staging/bwiki/混乱行至深处.json')
        background=queue_unassigned(s)
        typer.echo(json.dumps({'tasks':len(plan),'jobs':sum(len(p['pass1'])+len(p['pass2'])+1 for p in plan),'background':background,'suspect_first_task_instances':findings['suspect_instances']},ensure_ascii=False))

@app.command('run')
def run_cmd(batches:int=typer.Option(...),db:Path=DB,endpoint:str='http://127.0.0.1:8339/v1',model:str='Qwen3.5-9B-Q4_K_M',provider:str='local',
            key_file:Path|None=None,max_cost:float=0,max_tokens:int=2048,input_price:float|None=None,output_price:float|None=None,scope:str='first_task',context:int=24000,failed_only:bool=False,pass_number:int|None=None):
    from .providers import Provider
    from .jobs import run
    with AuditStore(db) as s:
        revisions=s.setting('model_revisions') or {}
        revision=revisions.get(model)
        if provider=='deepseek':revision=(s.setting('deepseek_pricing') or {}).get('version')
        typer.echo(json.dumps(run(s,Provider(endpoint,model,provider,key_file,input_price,output_price,revision),batches,max_tokens,max_cost,scope,context,failed_only,pass_number),ensure_ascii=False))

@app.command('status')
def status(db:Path=DB):
    from .report import report
    with AuditStore(db) as s:typer.echo(json.dumps(report(s),ensure_ascii=False,indent=2))

@app.command('report')
def report_cmd(db:Path=DB,output:Path=Path('data/audit/audit-report.json')):
    from .report import report
    from astralogue.adapters.hf import write
    with AuditStore(db) as s:write(output,report(s))
    typer.echo(str(output))

@app.command('pause')
def pause(db:Path=DB):
    with AuditStore(db) as s:s.setting('run_state','paused')

@app.command('cancel')
def cancel(db:Path=DB):
    with AuditStore(db) as s:s.setting('run_state','cancelled')

@app.command('webui')
def webui(db:Path=DB,port:int=8340):
    from .webui import serve
    serve(db,port)


@app.command('discover')
def discover_cmd(db:Path=DB,pack:Path=Path('data/packs/prologue-exploration-v112.storypack'),page:Path=Path('data/staging/bwiki/混乱行至深处.json')):
    """从本地固定版本折叠结构生成待审核提案，不联网或调用模型。"""
    from .findings import discover
    with AuditStore(db) as s:
        result=discover(s,pack,page)
        typer.echo(json.dumps({k:v for k,v in result.items() if k not in {'path','audit_edges'}},ensure_ascii=False))

@app.command('export-patch')
def export_patch_cmd(proposal:str,output:Path,pack:Path=Path('data/packs/prologue-exploration-v112.storypack'),db:Path=DB):
    from .review import export_patch
    from astralogue.storypack import StoryPack
    from astralogue.adapters.hf import write
    from astralogue.narrative.patch import validate_patch
    with AuditStore(db) as s,StoryPack(pack) as p:
        b=p.bundle();patch=export_patch(s,proposal,b);result=validate_patch(b,patch)
        if not result['valid']:raise ValueError(str(result['errors']))
        write(output,patch)


@app.command('rebuild')
def rebuild(output:Path,db:Path=DB,pack:Path=Path('data/packs/prologue-exploration-v112.storypack')):
    from .cleanup import compile_cleanup
    from .review import export_patch
    from astralogue.storypack import StoryPack
    from astralogue.compiler import compile_story
    if output.resolve()==pack.resolve():raise ValueError('Rebuild must preserve published source pack')
    with AuditStore(db) as s,StoryPack(pack) as p:
        b=p.bundle();ids=[r[0] for r in s.db.execute("SELECT id FROM proposals WHERE status='approved' ORDER BY id")]
        if not ids:raise ValueError('No human-approved proposals; published Reader remains unchanged')
        patches=[export_patch(s,pid,b) for pid in ids]
        rebuilt=compile_cleanup(b,patches);compile_story(rebuilt,output)
        typer.echo(json.dumps(rebuilt.metadata['audit_cleanup'],ensure_ascii=False))


@app.command('publish')
def publish_cmd(db:Path=DB):
    """将已批准提案增量发布至当前启动器数据包。"""
    from .publication import publish_approved
    from astralogue.model import load_json
    root=Path(__file__).resolve().parents[3]
    target=root/load_json(root/'data/launcher.json')['pack']
    with AuditStore(db) as s:
        s.setting('publication_pack',str(target.resolve()))
        ids=[r[0] for r in s.db.execute("SELECT id FROM proposals WHERE status='approved' ORDER BY reviewed_at,id")]
        typer.echo(json.dumps(publish_approved(s,ids),ensure_ascii=False))


@app.command('history')
def history_cmd(db:Path=DB):
    import sqlite3
    with AuditStore(db) as s:path=s.setting('publication_pack')
    if not path:raise ValueError('尚未启用增量发布')
    con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        rows=con.execute('SELECT revision,proposal,at,length(delta),rolled_back FROM reader_revisions ORDER BY revision DESC').fetchall()
        typer.echo(json.dumps(rows,ensure_ascii=False))
    finally:con.close()


@app.command('rollback')
def rollback_cmd(db:Path=DB):
    from .publication import rollback
    from astralogue.storypack import StoryPack
    with AuditStore(db) as s:
        path=s.setting('publication_pack')
        if not path:raise ValueError('尚未启用增量发布')
        with StoryPack(Path(path)) as p:
            row=p.con.execute('SELECT revision,proposal FROM reader_revisions WHERE rolled_back=0 ORDER BY revision DESC LIMIT 1').fetchone()
            if not row:raise ValueError('没有可回滚的修订')
            revision,proposal=row
        rollback(path)
        with s.db:s.db.execute("UPDATE publications SET status='rolled_back',result=? WHERE proposal=?",(json.dumps({'status':'rolled_back','revision':revision}),proposal))
        typer.echo('已回滚修订 '+str(revision)+'；若存档位于该修订新增节点，需恢复到兼容位置后继续。')
