"""Bounded MediaWiki retrieval and explicit cached alignment commands."""
from pathlib import Path
from urllib.parse import urlencode,quote
from urllib.robotparser import RobotFileParser
from datetime import datetime,timezone
import json
import typer
from astralogue.model import load_json,file_hash
from . import parse,align,build,review,report
app=typer.Typer(no_args_is_help=True)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

@app.command()
def fetch(page:str,output:Path,proxy:str|None=None):
    from astralogue.http import verified_opener
    from astralogue.cli import errors
    with errors():
        if output.exists():raise ValueError('Use cached snapshot or a new output path')
        base='https://honkai-star-rail.fandom.com';op=verified_opener(proxy)
        robot=RobotFileParser();robot.parse(op.open(base+'/robots.txt',timeout=20).read().decode('utf8').splitlines())
        url=base+'/api.php?'+urlencode({'action':'query','titles':page,'prop':'revisions','rvprop':'ids|content','rvslots':'main','format':'json'})
        if not robot.can_fetch('Astralogue',url):raise ValueError('robots disallows retrieval')
        raw=json.loads(op.open(url,timeout=30).read());pages=raw['query']['pages']
        if len(pages)!=1:raise ValueError('Page identity ambiguous')
        p=next(iter(pages.values()));rev=p['revisions'][0]
        write(output,{'format':'wikitext','url':base+'/wiki/'+quote(page),'page_id':p['pageid'],'revision_id':rev['revid'],'title':p['title'],'content':rev['slots']['main']['*'],'fetched_at':datetime.now(timezone.utc).isoformat(),'raw_api':raw,'license':'Review current wiki attribution/license before redistribution'})

@app.command('parse')
def parse_cmd(snapshot:Path,output:Path):
    from astralogue.cli import errors
    with errors():write(output,parse(load_json(snapshot)))
@app.command('align')
def align_cmd(parsed:Path,source:Path,english:Path,output:Path):
    from astralogue.cli import errors
    with errors():write(output,align(load_json(parsed),source,english))
@app.command('report')
def report_cmd(alignment:Path):typer.echo(json.dumps(report(load_json(alignment))))
@app.command('review')
def review_cmd(alignment:Path,decisions:Path,output:Path):
    from astralogue.cli import errors
    with errors():write(output,review(load_json(alignment),load_json(decisions)))
@app.command('build')
def build_cmd(alignment:Path,source:Path,output:Path,force:bool=False):
    from astralogue.cli import errors
    from astralogue.compiler import compile_story
    with errors():typer.echo(json.dumps(compile_story(build(load_json(alignment),source),output,force=force)['counts']))
