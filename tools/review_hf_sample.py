"""Targeted source review, not population accuracy or community endorsement."""
from pathlib import Path
from astralogue.model import load_json
from astralogue.adapters.hf import write
from astralogue.storypack import StoryPack

source=Path('data/raw/hsr-mainline')
rows={r['TalkSentenceID']:r for r in load_json(source/'ExcelOutput/TalkSentenceConfig.json') if 'TalkSentenceID' in r}
chs=load_json(source/'TextMap/TextMapCHS.json');records=[]
checks=[('002_漩涡止于中心',83,100020329,'CONTROL_CONTEXT_SUPPORTED'),('002_漩涡止于中心',91,100020340,'CONTROL_CONTEXT_SUPPORTED'),('002_漩涡止于中心',73,100020324,'NATIVE_FIELD_SUPPORTED'),('002_漩涡止于中心',64,100020315,'NATIVE_FIELD_SUPPORTED'),('001_混乱行至深处',128,100020104,'CONTROL_CONTEXT_SUPPORTED'),('001_混乱行至深处',30,100019620,'INSTANCE_CONTEXT_UNDETERMINED'),('001_混乱行至深处',148,None,'UNRESOLVED_GENDER_VARIANTS'),('001_混乱行至深处',115,200011602,'CONTROL_CONTEXT_SUPPORTED')]
with StoryPack(Path('data/packs/hsr-mainline-reader.storypack')) as native:
    native_nodes={n.data.get('talk_sentence_id'):n for n in native.bundle().nodes if n.data.get('native_evidence')}
    for stem,i,sid,status in checks:
        a=load_json(Path('data/staging/hf-aligned')/(stem+'.json'));b=a['bindings']['tree/'+str(i)]
        assert b['selected']==sid
        proof=None
        if status=='CONTROL_CONTEXT_SUPPORTED':
            proof=[p for p in a['game_evidence']['pairs'] if sid in [p['source'],p['target']]]
            assert proof
        elif status=='NATIVE_FIELD_SUPPORTED':
            ev=native_nodes[sid].data['native_evidence'];assert ev['object']['talk_sentence_id']==sid
            proof={k:ev[k] for k in ['serialized_file','root','reference','track','clip']}
        records.append({'file':a['report']['file'],'index':i,'selected':sid,'status':status,'hf':b['original'],'catalog':chs[str(rows[sid]['TalkSentenceText']['Hash'])] if sid else None,'candidate_ids':[c['id'] for c in b['candidates']+b['fuzzy_candidates']],'proof':proof})
write(Path('data/hf-source-review.json'),{'sampling':'targeted strata; nonrandom, not corpus accuracy','supported':6,'wrong_found':0,'undetermined_or_unresolved':2,'records':records,'community_reviewed':False})
print('Targeted source checks: 6 supported, 0 wrong found, 2 unresolved; not a population accuracy estimate')
