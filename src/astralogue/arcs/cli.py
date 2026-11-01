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
def build_cmd(arc_id:str='auto',source:Path=Path('data/raw/hsr-mainline'),dataset:Path=Path('data/external/hf-trailblaze'),alignments:Path=Path('data/staging/hf-aligned'),control_pack:Path=Path('data/packs/hsr-mainline-m59.storypack'),output:Path=Path('data/packs/prologue-player.storypack'),variant_review:Path=Path('docs/patches/prologue-version-review.json'),player:bool=True,snapshots:Path=Path('data/staging/bwiki'),avatar_config:Path=Path('data/staging/bwiki/AvatarConfig.json'),force:bool=False):
    from astralogue.cli import errors
    from astralogue.storypack import StoryPack
    from astralogue.compiler import compile_story
    with errors(),StoryPack(control_pack) as pack:
        inv=inventory(source,dataset);plan=select(inv) if arc_id=='auto' else next(p for c in inv['chapters'] for p in c['plans'] if p['id']==arc_id)
        if not plan['feasible']:raise ValueError('Chapter boundary or required transcript missing')
        b=compile_arc(plan,source,dataset,alignments,pack,load_json(variant_review) if variant_review.exists() else None)
        if player:
            from .enrich import enrich
            enrich(b,source,dataset,snapshots,avatar_config,pack)
        compile_story(b,output,force=force)
        typer.echo(json.dumps(b.metadata['story_arcs'][b.metadata['narrative']['entries']['reader']]['summary'],ensure_ascii=False))
@app.command('play')
def play_cmd(pack:Path=Path('data/packs/prologue-player.storypack'),debug:bool=False,accounts_dir:Path=Path('saves/accounts')):
    from astralogue.accounts import launch
    return launch(pack,accounts_dir,debug)

@app.command('audit')
def audit_cmd(save:Path,pack:Path=Path('data/packs/prologue-player.storypack'),output:Path=Path('data/arc-edge-audit.json')):
    from astralogue.storypack import StoryPack
    from .session import ArcSession
    with StoryPack(pack) as sp:
        rt=ArcSession.load(sp,save);write(output,{'pack_id':sp.metadata['pack_id'],'progress':rt.progress(),'edges':rt.traversal,'native_completion':False})

@app.command('migrate-save')
def migrate_cmd(save:Path,old_pack:Path,pack:Path,output:Path):
    """显式迁移相同来源章节的旧进度；保留旧审计，补全身份，回溯从迁移点起。"""
    from astralogue.storypack import StoryPack
    from astralogue.cli import errors
    from .session import migrate_save
    with errors(),StoryPack(old_pack) as old,StoryPack(pack) as new:
        rt=migrate_save(old,new,save,output)
        typer.echo(json.dumps({'output':str(output),'progress':rt.progress(),'profile_completion_required':rt.profile_migration,
            'notice':'旧历史审计完整保留；不能跨更换后的图回溯。原存档未修改。'},ensure_ascii=False))
