"""Pinned Hugging Face JSON snapshots; never execute repository code."""
from pathlib import Path,PurePosixPath
from urllib.parse import quote
import json
from astralogue.http import verified_opener
from astralogue.model import load_json,file_hash

REPO='yuhuanstudio/Honkai_StarRail_Trailblaze_Mission_zhtw'
SAMPLES=['missions/002_漩涡止于中心.json','missions/001_混乱行至深处.json']

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    temporary.replace(path)

def safe_path(root,name):
    if not isinstance(name,str) or '\\' in name or ':' in name:raise ValueError('Unsafe repository path')
    logical=PurePosixPath(name)
    if logical.is_absolute() or '..' in logical.parts:raise ValueError('Unsafe repository path')
    target=(root/name).resolve()
    if not target.is_relative_to(root.resolve()):raise ValueError('Repository path escapes snapshot root')
    return target

def verify(root,paths=None):
    manifest=load_json(root/'source-manifest.json')
    if manifest.get('repository')!=REPO:raise ValueError('HF repository mismatch')
    for name in paths or manifest['files']:
        path=safe_path(root,name)
        if name not in manifest['files'] or not path.is_file() or file_hash(path)!=manifest['files'][name]['sha256']:raise ValueError('HF file missing/hash mismatch: '+name)
    return manifest

def fetch(root:Path,paths=None,proxy=None,revision=None):
    paths=paths or SAMPLES
    if (root/'source-manifest.json').is_file():
        existing=load_json(root/'source-manifest.json')
        if revision and revision!=existing['revision']:raise ValueError('Use a separate directory for another HF revision')
        if all(p in existing['files'] for p in paths):return verify(root)
    root.mkdir(parents=True,exist_ok=True)
    op=verified_opener(proxy)
    info_path=root/'repository.json'
    info=load_json(info_path) if info_path.exists() else json.loads(op.open('https://huggingface.co/api/datasets/'+REPO,timeout=30).read())
    sha=revision or info['sha']
    if sha!=info['sha']:raise ValueError('Repository metadata revision does not match requested revision')
    write(info_path,info)
    allowed={s['rfilename'] for s in info['siblings']}
    manifest=load_json(root/'source-manifest.json') if (root/'source-manifest.json').exists() else {'repository':REPO,'revision':sha,'author':'yuhuanstudio','license_metadata':info.get('cardData',{}),'scope':'CHS ordered transcript through 3.0; first options only; incomplete branches','files':{}}
    for name in paths+['README.md']:
        if name not in allowed:raise ValueError('Path absent from pinned repository: '+name)
        if name in manifest['files']:
            verify(root,[name]);continue
        if not (name.startswith('missions/') and name.endswith('.json') or name=='README.md'):raise ValueError('Only missions JSON and attribution README allowed')
        if '..' in PurePosixPath(name).parts:raise ValueError('Unsafe repository path')
        target=safe_path(root,name);target.parent.mkdir(parents=True,exist_ok=True)
        url='https://huggingface.co/datasets/'+REPO+'/resolve/'+sha+'/'+quote(name,safe='/')
        raw=op.open(url,timeout=40).read()
        if name.endswith('.json'):json.loads(raw)
        partial=target.with_suffix(target.suffix+'.partial');partial.write_bytes(raw);partial.replace(target)
        manifest['files'][name]={'sha256':file_hash(target),'bytes':len(raw),'url':url}
        write(root/'source-manifest.json',manifest)
    return verify(root,paths)


def import_local(root,revision,paths=None):
    import re
    if not re.fullmatch(r'[0-9a-f]{40}',revision):raise ValueError('Explicit 40-character HF commit required')
    if (root/'source-manifest.json').exists():raise ValueError('Existing manifest must be verified, not overwritten')
    paths=paths or SAMPLES
    manifest={'repository':REPO,'revision':revision,'author':'yuhuanstudio','license_metadata':{'note':'Inspect supplied README; repository metadata tag does not license game contents'},'scope':'First-option transcript through 3.0; manually supplied, remote contents not authenticated','files':{}}
    for name in paths+(['README.md'] if (root/'README.md').is_file() else []):
        if not (name.startswith('missions/') and name.endswith('.json') or name=='README.md') or '..' in PurePosixPath(name).parts:raise ValueError('Unsupported import path')
        path=safe_path(root,name)
        if name.endswith('.json'):load_json(path)
        manifest['files'][name]={'sha256':file_hash(path),'bytes':path.stat().st_size,'acquisition':'manual_user_supplied'}
    write(root/'source-manifest.json',manifest)
    return verify(root)
