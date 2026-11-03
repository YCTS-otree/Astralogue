"""Explicit worker lifecycle; cached parsing never starts a network worker."""
from pathlib import Path
import json
import os
import subprocess
import sys
import typer
from .pilot import Pilot

app = typer.Typer(no_args_is_help=True)
pilot_app = typer.Typer(no_args_is_help=True)
app.add_typer(pilot_app, name='pilot')
ROOT = Path('data/staging/bwiki-pilot')


@pilot_app.command('start')
def start(chapter: str = '100001', root: Path = ROOT, proxy: str | None = None):
    if chapter != '100001': raise typer.BadParameter('Only chapter 100001 is enabled')
    p = Pilot(root)
    # No spawn if another worker owns the lock.
    from .pilot import single_instance
    with single_instance(p.root/'worker.lock'): p.state('running')
    p.close()
    args = [sys.executable,'-m','astralogue','bwiki','pilot','worker','--root',str(root.resolve())]
    if proxy: args += ['--proxy',proxy]
    log = root/'worker.log'
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name=='nt' else 0
    with log.open('ab') as f:
        child = subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=f,stderr=f,creationflags=flags,
                                 start_new_session=os.name!='nt')
    typer.echo(f'Pilot started: PID {child.pid}')


@pilot_app.command('resume')
def resume(root: Path = ROOT, proxy: str | None = None): start('100001',root,proxy)


@pilot_app.command('status')
def status(root: Path = ROOT):
    p = Pilot(root)
    try: typer.echo(json.dumps(p.status(),ensure_ascii=False,indent=2))
    finally: p.close()


@pilot_app.command('pause')
def pause(root: Path = ROOT):
    p = Pilot(root); p.state('paused'); p.close()


@pilot_app.command('stop')
def stop(root: Path = ROOT):
    p = Pilot(root); p.state('stopped'); p.close()


@pilot_app.command('import')
def import_cmd(path: Path, root: Path = ROOT):
    p = Pilot(root)
    try:
        from .pilot import single_instance
        with single_instance(p.root/'worker.lock'):
            typer.echo(p.import_page(path));p.parse_cached()
    finally: p.close()


@pilot_app.command('parse')
def parse(root: Path = ROOT, title: str | None = None):
    p = Pilot(root)
    try:
        from .pilot import single_instance
        with single_instance(p.root/'worker.lock'):
            if title:
                row=p.db.execute('SELECT * FROM pages WHERE title=?',(title,)).fetchone()
                if not row or not row['cache']: raise ValueError('No cached page')
                from astralogue.model import file_hash
                if file_hash(p.root/row['cache'])!=row['sha256']: raise ValueError('Cache integrity failure')
                with p.db: p.db.execute("UPDATE pages SET status='FETCHED' WHERE title=?",(title,))
            p.recover(); p.parse_cached()
    finally: p.close()


@pilot_app.command('build')
def build(pack: Path = Path('data/packs/prologue-player.storypack'), output: Path = Path('data/packs/prologue-exploration.storypack'), root: Path = ROOT):
    from astralogue.storypack import StoryPack
    from astralogue.compiler import compile_story
    from astralogue.arcs.exploration import compile_exploration
    from astralogue.model import file_hash
    if output.resolve()==pack.resolve(): raise ValueError('Keep original pack for existing accounts')
    p=Pilot(root)
    try:
        paths=[]
        for row in p.status()['pages']:
            if row['title']=='今天是昨天的明天' or row['status']!='VALIDATED': continue
            path=p.root/row['cache']
            if file_hash(path)!=row['sha256']: raise ValueError('Cache hash conflict')
            paths.append(path)
        with StoryPack(pack) as sp:
            b=sp.bundle()
            if 'free_exploration' in b.metadata: raise ValueError('Build from original player pack')
            report=compile_exploration(b,paths);compile_story(b,output)
            typer.echo(json.dumps(report,ensure_ascii=False,indent=2))
    finally: p.close()


@pilot_app.command('worker',hidden=True)
def worker(root: Path = ROOT, proxy: str | None = None):
    p = Pilot(root)
    try: p.run(proxy)
    finally: p.close()


@pilot_app.command('report')
def report_cmd(root: Path = ROOT, pack: Path = Path('data/packs/prologue-player.storypack'), dataset: Path = Path('data/external/hf-trailblaze'), output: Path = Path('data/bwiki-pilot-report.json')):
    from .pilot_report import report
    from astralogue.adapters.hf import write
    write(output,report(root,pack,dataset));typer.echo(str(output))
