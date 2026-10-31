from pathlib import Path
import json
import typer
from . import inventory,select,compile_arc
from astralogue.adapters.hf import write
from astralogue.model import load_json
app=typer.Typer(no_args_is_help=True)
@app.command('list')
def list_cmd(source:Path=Path('data/raw/hsr-mainline'),dataset:Path=Path('data/external/hf-trailblaze'),output:Path=Path('data/m9-inventory.json')):
    inv=inventory(source,dataset);write(output,inv)
    for c in inv['chapters']:
        typer.echo(json.dumps({'chapter':c['title'],'plans':[{'id':p['id'],'feasible':p['feasible'],'tasks':len(p['tasks'])} for p in c['plans']]},ensure_ascii=False))
@app.command('inspect')
def inspect_cmd(arc_id:str,source:Path=Path('data/raw/hsr-mainline'),dataset:Path=Path('data/external/hf-trailblaze')):
    inv=inventory(source,dataset);plan=next(p for c in inv['chapters'] for p in c['plans'] if p['id']==arc_id);typer.echo(json.dumps(plan,ensure_ascii=False,indent=2))
@app.command('build')
def build_cmd(arc_id:str='auto',source:Path=Path('data/raw/hsr-mainline'),dataset:Path=Path('data/external/hf-trailblaze'),alignments:Path=Path('data/staging/hf-aligned'),control_pack:Path=Path('data/packs/hsr-mainline-m59.storypack'),output:Path=Path('data/packs/prologue-arc.storypack'),variant_review:Path=Path('docs/patches/prologue-version-review.json'),force:bool=False):
    from astralogue.cli import errors
    from astralogue.storypack import StoryPack
    from astralogue.compiler import compile_story
    with errors(),StoryPack(control_pack) as pack:
        inv=inventory(source,dataset);plan=select(inv) if arc_id=='auto' else next(p for c in inv['chapters'] for p in c['plans'] if p['id']==arc_id)
        if not plan['feasible']:raise ValueError('Chapter boundary or required transcript missing')
        b=compile_arc(plan,source,dataset,alignments,pack,load_json(variant_review) if variant_review.exists() else None);compile_story(b,output,force=force)
        typer.echo(json.dumps(b.metadata['story_arcs'][b.metadata['narrative']['entries']['reader']]['summary'],ensure_ascii=False))
@app.command('play')
def play_cmd(pack:Path=Path('data/packs/prologue-arc.storypack')):
    from astralogue.narrative.cli import play
    return play(pack=pack,mode='reader',save_file=Path('saves/arc/latest.save.json'),autosave=Path('saves/arc/autosave.save.json'))

@app.command('audit')
def audit_cmd(save:Path,pack:Path=Path('data/packs/prologue-arc.storypack'),output:Path=Path('data/arc-edge-audit.json')):
    from astralogue.storypack import StoryPack
    from .session import ArcSession
    with StoryPack(pack) as sp:
        rt=ArcSession.load(sp,save);write(output,{'pack_id':sp.metadata['pack_id'],'progress':rt.progress(),'edges':rt.traversal,'native_completion':False})
