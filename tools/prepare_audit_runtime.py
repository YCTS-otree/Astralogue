"""Stage official llama.cpp Windows CUDA release assets, verify hashes and ZIP paths."""
from pathlib import Path
import hashlib
import json
import zipfile
import urllib.request
from astralogue.http import verified_opener
from astralogue.model import load_json,file_hash
from astralogue.adapters.hf import write

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--china-proxy',action='store_true');args=parser.parse_args()
    rel=load_json(Path('data/audit/llama-gpu-release.json'));folder=Path('data/tools/llama.cpp')/rel['tag_name'];folder.mkdir(parents=True,exist_ok=True)
    output=folder/'runtime';output.mkdir(exist_ok=True);manifest=[]
    for asset in rel['assets']:
        if not (asset['name'].endswith('win-cuda-12.4-x64.zip')) or asset['name'].startswith('cudart-'):continue
        path=folder/asset['name']
        if not path.exists():
            for proxy in [None,'http://127.0.0.1:10808']:
                try:
                    url=('https://gh-proxy.com/' if args.china_proxy else '')+asset['browser_download_url']
                    temp=path.with_suffix('.part')
                    while (offset:=temp.stat().st_size if temp.exists() else 0)<asset['size']:
                        end=min(asset['size']-1,offset+32*1024*1024-1)
                        request=urllib.request.Request(url,headers={'Range':f'bytes={offset}-{end}'})
                        with verified_opener(proxy).open(request,timeout=45) as r:
                            if r.status==206 and not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Runtime download range mismatch')
                            with temp.open('ab' if offset and r.status==206 else 'wb') as f:
                                while chunk:=r.read(4*1024*1024):f.write(chunk)
                    path.with_suffix('.part').replace(path);break
                except Exception:
                    if proxy:raise
        actual=file_hash(path);expected=asset.get('digest')
        if expected and expected!='sha256:'+actual:raise ValueError('Official runtime release hash mismatch')
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                target=(output/member.filename).resolve()
                if not target.is_relative_to(output.resolve()):raise ValueError('Unsafe ZIP path')
            archive.extractall(output)
        manifest.append({'url':asset['browser_download_url'],'name':asset['name'],'sha256':actual,'publisher_digest':expected})
        print('verified '+asset['name'],flush=True)
    write(folder/'source-manifest.json',{'upstream':'https://github.com/ggml-org/llama.cpp','release':rel['tag_name'],'assets':manifest,'license':'MIT'})
    print(str(output.resolve()),flush=True)
