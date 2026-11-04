"""Pinned official ModelScope file hashes, bounded parallel downloads; no remote code."""
from pathlib import Path
import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from astralogue.http import verified_opener
from astralogue.model import load_json,file_hash
from astralogue.adapters.hf import write


def download(entry,folder,repo='Qwen/Qwen3.5-9B'):
    name=entry['Path']
    if Path(name).name!=name:raise ValueError('Unexpected model path')
    path=folder/name;expected=entry['Sha256']
    if path.exists() and file_hash(path)==expected:return name
    temp=path.with_suffix(path.suffix+'.part')
    for attempt in range(3):
        try:
            url='https://modelscope.cn/api/v1/models/'+repo+'/repo?'+urllib.parse.urlencode({'Revision':entry['Revision'],'FilePath':name})
            while (offset:=temp.stat().st_size if temp.exists() else 0)<entry['Size']:
                end=min(entry['Size']-1,offset+64*1024*1024-1)
                req=urllib.request.Request(url,headers={'Range':f'bytes={offset}-{end}'})
                with verified_opener('http://127.0.0.1:10808' if attempt else None).open(req,timeout=45) as r:
                    if r.status==206 and not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Incorrect partial response offset')
                    append=offset>0 and r.status==206
                    with temp.open('ab' if append else 'wb') as f:
                        while chunk:=r.read(4*1024*1024):f.write(chunk)
            if temp.stat().st_size!=entry['Size'] or file_hash(temp)!=expected:raise ValueError('Model content hash mismatch')
            temp.replace(path);print('verified '+name,flush=True);return name
        except Exception:
            if attempt==2:raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--gguf',action='store_true');args=parser.parse_args()
    manifest=load_json(Path('data/audit/qwen9b_gguf.json' if args.gguf else 'data/audit/qwen9b-modelscope-files.json'))
    repo='unsloth/Qwen3.5-9B-GGUF' if args.gguf else 'Qwen/Qwen3.5-9B'
    folder=Path('data/models/Qwen3.5-9B-GGUF' if args.gguf else 'data/models/Qwen3.5-9B');folder.mkdir(parents=True,exist_ok=True)
    files=[f for f in manifest['Data']['Files'] if f['Type']=='blob' and ((f['Path']=='Qwen3.5-9B-Q4_K_M.gguf') if args.gguf else (f['Path'].endswith(('.safetensors','.json','.jinja','.txt')) or f['Path'] in {'LICENSE','README.md'}))]
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda e:download(e,folder,repo),files))
    write(folder/'source-manifest.json',{'model':repo,'upstream':'Qwen/Qwen3.5-9B','source':'ModelScope','files':files,'trust_remote_code':False})
    print('Official 9B model verified; inference is a separate explicit action.')
