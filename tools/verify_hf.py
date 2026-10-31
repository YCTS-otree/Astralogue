"""Bounded verification of HF excerpts, independent controls and offline CLI."""
from pathlib import Path
from collections import Counter
import argparse,json,os,subprocess,sys,tempfile
from astralogue.model import load_json
from astralogue.adapters.hf import write,SAMPLES
from astralogue.storypack import StoryPack
from astralogue.runtime import Runtime,DialogueEvent,ChoiceEvent,EndEvent,BlockedEvent
from astralogue.narrative import audit


def run(pack,mission,save):
    rt=Runtime(pack,mission);ids=[];input_=[]
    for _ in range(300):
        event=rt.next()
        if isinstance(event,DialogueEvent):ids.append(pack.node(event.node).data['talk_sentence_id']);input_.append('')
        elif isinstance(event,ChoiceEvent):
            if len(event.options)!=1:raise AssertionError('HF excerpt must not invent options')
            node=pack.node(event.node)
            if node.data.get('reader_action')=='hf_option_excerpt':ids.append(node.data['talk_sentence_id'])
            rt.choose(event.options[0].value);input_.append('1')
        else:
            assert isinstance(event,EndEvent),event
            rt.save(save);return ids,rt,'\n'.join(input_+['',''])
    raise AssertionError('Excerpt exceeded 300 event bound')


def verify_one(alignment_path,pack_path,records):
    a=load_json(alignment_path);result={'alignment':str(alignment_path),'report':a['report'],'runs':[]}
    with StoryPack(pack_path) as pack:
        entries=[(mid,mode) for mid,mode in pack.metadata['narrative']['modes'].items() if mode.get('scope')=='hf_contiguous_excerpt']
        def novelty(mid):
            ns=mid.removesuffix(':reader')+':'
            return len({(v['hf_relation']['source_id'],v['hf_relation']['target_id']) for k,v in pack.metadata['narrative']['relations'].items() if k.startswith(ns) and v.get('hf_relation',{}).get('status')=='HF_ORDER_ONLY' and not v.get('previously_available')})
        novel_entry=max((mid for mid,_ in entries),key=novelty)
        selected_ids=set();novel_pairs=set()
        for i,(mid,mode) in enumerate(entries):
            save=records/(pack_path.stem+'-'+str(i)+'.save.json');ids,rt,input_=run(pack,mid,save)
            expected=[a['bindings']['tree/'+str(j)]['selected'] for j in mode['hf_indices']]
            assert ids==expected,(mid,ids,expected)
            selected_ids.update(ids)
            trace=audit(pack,load_json(save));assert trace['reading_end_reached'] and not trace['original_game_completion_proven']
            assert isinstance(Runtime.load(pack,save).next(),EndEvent)
            rt.back();assert isinstance(rt.next(),ChoiceEvent)
            result['runs'].append({'mission':mid,'indices':mode['hf_indices'],'ids':ids,'actions':dict(Counter(r['action'] for r in trace['records']))})
            if mid in {pack.metadata['narrative']['entries']['reader'],novel_entry}:
                suffix='' if mid==pack.metadata['narrative']['entries']['reader'] else '-novel'
                write(records/(pack_path.stem+suffix+'-audit.json'),trace)
                env={**os.environ,'PYTHONIOENCODING':'utf-8','HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'}
                for key in list(env):
                    if key.startswith('ASTRALOGUE_'):env.pop(key)
                with tempfile.TemporaryDirectory() as cwd:
                    cli=subprocess.run([sys.executable,'-m','astralogue','reader','play','--pack',str(pack_path.resolve()),'--autosave',str((records/(pack_path.stem+suffix+'-cli.save.json')).resolve())],cwd=cwd,env=env,input=input_,encoding='utf8',text=True,capture_output=True,timeout=30)
                (records/(pack_path.stem+suffix+'-cli.txt')).write_text(cli.stdout+cli.stderr,encoding='utf8')
                assert cli.returncode==0 and 'Reader 所选文字阅读段结束' in cli.stdout,cli.stderr
                result['default_cli' if not suffix else 'novel_cli']={'new_external_pair_count':novelty(mid),'exit_code':cli.returncode,'mission':mid,'ids':ids}
        result.update(runtime_completed_excerpts=len(entries),distinct_reader_ids=len(selected_ids),full_dataset_scope_completed=False,full_game_task_completed=False,pack_id=pack.metadata['pack_id'])
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--alignments',type=Path,default=Path('data/staging/hf-aligned'));p.add_argument('--packs',type=Path,default=Path('data/packs'));p.add_argument('--records',type=Path,default=Path('data/staging/hf-playback'));p.add_argument('--output',type=Path,default=Path('data/m8-hf-runtime.json'));args=p.parse_args();args.records.mkdir(parents=True,exist_ok=True)
    results=[verify_one(args.alignments/(Path(name).stem+'.json'),args.packs/('hf-'+Path(name).name[:3]+'.storypack'),args.records) for name in SAMPLES]
    write(args.output,{'samples':results,'scope':'HF excerpts only, not full dataset or game tasks'})
    print(json.dumps([{k:r[k] for k in ['runtime_completed_excerpts','distinct_reader_ids','full_game_task_completed']} for r in results]))
if __name__=='__main__':main()
