"""Explicit, bounded source acquisition. Rebuild/play never invoke this script."""
import argparse
import hashlib
import time
from pathlib import Path
from astralogue.adapters.wiki.bwiki import fetch
from astralogue.adapters.hf import write
from astralogue.http import verified_opener
from astralogue.model import load_json, file_hash

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy');parser.add_argument('--output',type=Path,default=Path('data/staging/bwiki'))
    parser.add_argument('--source',type=Path,default=Path('data/raw/hsr-mainline'));args=parser.parse_args()
    source=load_json(args.source/'source.json');records=[]
    manifest=args.output/'source-manifest.json'
    if manifest.exists():
        for entry in load_json(manifest)['files']:
            path=args.output/entry['file']
            if not path.is_file() or file_hash(path)!=entry['sha256']:raise ValueError('Cached source hash mismatch: '+entry['file'])
    for title in ['混乱行至深处','漩涡止于中心']:
        path=args.output/(title+'.json');cached=path.exists();p=fetch(title,path,args.proxy)['parse']
        records.append({'file':path.name,'sha256':file_hash(path),'page_id':p['pageid'],'revision_id':p['revid']})
        if not cached:time.sleep(1)
    path=args.output/'AvatarConfig.json'
    if not path.exists():
        url=f"https://raw.githubusercontent.com/DimbreathBot/TurnBasedGameData/{source['revision']}/ExcelOutput/AvatarConfig.json"
        with verified_opener(args.proxy).open(url,timeout=30) as response:raw=response.read()
        path.write_bytes(raw)
    raw=path.read_bytes();expected=load_json(args.source/'resource-index.json')['files']['ExcelOutput/AvatarConfig.json']['sha']
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=expected:raise ValueError('Avatar source blob mismatch')
    records.append({'file':path.name,'sha256':file_hash(path),'source':source})
    write(args.output/'source-manifest.json',{'files':records,'scope':'two BWIKI page snapshots and one pinned AvatarConfig table; no asset rescan'})
    print('Player sources cached; all subsequent build/play steps are offline.')
