"""HF fetch once, then offline alignment/build with per-file checkpoints."""
from pathlib import Path
from typing import Annotated
import json
import typer
from astralogue.adapters.hf import SAMPLES,fetch,verify,write,import_local
from astralogue.model import load_json,file_hash,digest
app=typer.Typer(no_args_is_help=True,help='固定版本 HF 开拓任务转录；不访问 Wiki 源站')
DEFAULT=Path('data/external/hf-trailblaze')
@app.command('fetch')
def fetch_cmd(directory:Path=DEFAULT,proxy:str|None=None,all_missions:bool=False):
    from astralogue.cli import errors
    with errors():
        paths=SAMPLES
        if all_missions:
            info=load_json(directory/'repository.json')
            paths=[x['rfilename'] for x in info['siblings'] if x['rfilename'].startswith('missions/') and x['rfilename'].endswith('.json')]
        m=fetch(directory,paths,proxy);typer.echo(json.dumps({'revision':m['revision'],'verified_files':len(m['files'])}))
@app.command('import-local')
def import_cmd(directory:Path,revision:str):
    from astralogue.cli import errors
    with errors():typer.echo(json.dumps(import_local(directory,revision)))
@app.command('align')
def align_cmd(source:Path,control_pack:Path,directory:Path=DEFAULT,output_dir:Path=Path('data/staging/hf-aligned'),batch:bool=False,retry_failed:bool=False):
    from astralogue.cli import errors
    from astralogue.storypack import StoryPack
    from astralogue.adapters.wiki.index import DialogueIndex
    from .hf_alignment import GameEvidence,align_dataset,ALIGNER_VERSION
    with errors(),StoryPack(control_pack) as pack:
        manifest=verify(directory);index=DialogueIndex(source);evidence=GameEvidence(pack,source)
        paths=sorted(p for p in manifest['files'] if p.startswith('missions/') and p.endswith('.json')) if batch else SAMPLES
        context={'pack_id':pack.metadata['pack_id'],'chs':file_hash(source/'TextMap/TextMapCHS.json'),'sentences':file_hash(source/'ExcelOutput/TalkSentenceConfig.json'),'parser':ALIGNER_VERSION}
        checkpoint=[]
        for name in paths:
            out=output_dir/(Path(name).stem+'.json');failure=out.with_suffix('.failed.json');key=digest([context,manifest['files'][name]['sha256']])
            if out.exists() and load_json(out).get('cache_key')==key:
                checkpoint.append({'file':name,'state':'CACHED','report':load_json(out)['report']});continue
            if failure.exists() and not retry_failed and load_json(failure).get('cache_key')==key:
                checkpoint.append({'file':name,'state':'FAILED_CACHED'});continue
            try:
                aligned=align_dataset(directory,name,source,index,evidence);aligned['cache_key']=key;write(out,aligned)
                checkpoint.append({'file':name,'state':'ALIGNED','report':aligned['report']});failure.unlink(missing_ok=True)
            except (ValueError,KeyError,OSError,TypeError) as ex:
                write(failure,{'file':name,'cache_key':key,'error':str(ex)});checkpoint.append({'file':name,'state':'FAILED','error':str(ex)})
            write(output_dir/'batch-report.json',{'revision':manifest['revision'],'files':checkpoint,'complete':False})
            typer.echo(name+' '+checkpoint[-1]['state'])
        write(output_dir/'batch-report.json',{'revision':manifest['revision'],'files':checkpoint,'complete':True})
@app.command('build')
def build_cmd(alignment:Path,source:Path,control_pack:Path,output:Annotated[Path,typer.Option()],baseline_reader:list[Path]=typer.Option([]),force:bool=False):
    from astralogue.cli import errors
    from astralogue.storypack import StoryPack
    from astralogue.compiler import compile_story
    from .hf_alignment import compile_dataset_reader,previous_reader_pairs
    with errors(),StoryPack(control_pack) as pack:
        a=load_json(alignment)
        if file_hash(source/'TextMap/TextMapCHS.json')!=a['inputs']['chs'] or file_hash(source/'ExcelOutput/TalkSentenceConfig.json')!=a['inputs']['sentences']:raise ValueError('Stale alignment source')
        if pack.metadata['mission_manifest']['source']['revision']!=a['source']['revision']:raise ValueError('Control source revision mismatch')
        b,result=compile_dataset_reader(a,source,pack.bundle(),previous_reader_pairs(baseline_reader))
        result['pack_id']=compile_story(b,output,force=force)['pack_id'];write(output.with_suffix('.build.json'),result);typer.echo(json.dumps(result,ensure_ascii=False))
@app.command('report')
def report_cmd(alignment:Path):typer.echo(json.dumps(load_json(alignment)['report'],ensure_ascii=False,indent=2))
