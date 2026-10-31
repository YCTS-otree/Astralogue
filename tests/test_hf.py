"""HF snapshot integrity, conservative CHS candidates and real Reader regressions."""
import json
import os
from pathlib import Path
from copy import deepcopy
import pytest
from typer.testing import CliRunner
from astralogue.adapters.hf import REPO,fetch,verify,write,import_local
from astralogue.adapters.wiki.index import DialogueIndex
from astralogue.hsr.hf_alignment import convert,align_dataset,compile_dataset_reader
from astralogue.model import file_hash,load_json
from astralogue.cli import app

@pytest.fixture
def tiny(tmp_path):
    source=tmp_path/'source';root=tmp_path/'hf';name='missions/sample.json'
    write(source/'source.json',{'revision':'test','game_version':'test'})
    write(source/'TextMap/TextMapCHS.json',{'1':'结构中文甲乙丙','2':'结构中文甲乙丙','3':'角色甲','4':'角色乙','5':'A B','6':'结构中文甲乙丁'})
    write(source/'ExcelOutput/TalkSentenceConfig.json',[{'TalkSentenceID':1,'TalkSentenceText':{'Hash':1},'TextmapTalkSentenceName':{'Hash':3}},{'TalkSentenceID':2,'TalkSentenceText':{'Hash':2},'TextmapTalkSentenceName':{'Hash':4}},{'TalkSentenceID':3,'TalkSentenceText':{'Hash':5}},{'TalkSentenceID':4,'TalkSentenceText':{'Hash':6},'TextmapTalkSentenceName':{'Hash':3}}])
    write(root/name,{'title':'结构任务','story':[{'type':'對話','speaker':'角色甲','content':'结构中文甲乙丙'},{'type':'旁白','content':'结构说明'},{'type':'動畫','content':'结构演出'},{'type':'new','content':'未知结构'}],'url':'local:structural-evidence'})
    write(root/'source-manifest.json',{'repository':REPO,'revision':'a'*40,'author':'test','license_metadata':{},'scope':'first option only','files':{name:{'sha256':file_hash(root/name)}}})
    return source,root,name

def test_cached_fetch_is_offline_and_checks_every_hash(tiny,monkeypatch):
    _,root,name=tiny
    monkeypatch.setattr('astralogue.adapters.hf.verified_opener',lambda *a:pytest.fail('cache attempted network'))
    assert fetch(root,[name])['revision']=='a'*40
    (root/name).write_text('{}',encoding='utf8')
    with pytest.raises(ValueError,match='hash mismatch'):fetch(root,[name])

def test_adapter_preserves_raw_order_and_non_dialogue_types(tiny):
    _,root,name=tiny;p=convert(root,name)
    assert [n['type'] for n in p['tree']]==['dialogue','narration','animation','unknown']
    assert [n['position'] for n in p['tree']]==list(range(4))
    assert p['snapshot']['dataset']['file']==name and p['snapshot']['raw_json']['story'][0]==p['tree'][0]['raw']

def test_duplicate_candidates_survive_speaker_disambiguation(tiny):
    source,_,_=tiny;index=DialogueIndex(source)
    result=index.match('结构中文甲乙丙','角色甲')
    assert len(result['candidates'])==2 and result['selected']==1 and result['basis']=='exact_speaker'
    assert index.match('结构中文甲乙丙')['selected'] is None
    assert index.match('结构中文甲乙丙',owned={2})['selected']==2

def test_restricted_normalization_does_not_lowercase_or_guess(tiny):
    source,_,_=tiny;index=DialogueIndex(source)
    assert index.match('A\nB')['selected']==3
    assert index.match('a b')['selected'] is None

def test_single_fuzzy_candidate_never_auto_accepts(tiny):
    source,_,_=tiny;index=DialogueIndex(source)
    result=index.match('结构中文甲乙戊','角色甲',owned={1})
    assert result['selected'] is None and result['fuzzy_candidates']

def test_manual_import_is_explicit_and_hash_bound(tmp_path):
    root=tmp_path/'manual';write(root/'missions/sample.json',{'story':[]})
    m=import_local(root,'b'*40,['missions/sample.json'])
    assert m['files']['missions/sample.json']['acquisition']=='manual_user_supplied'
    with pytest.raises(ValueError):import_local(root,'b'*40,['missions/sample.json'])

def test_unsafe_manifest_path_is_rejected(tiny):
    _,root,_=tiny
    from astralogue.adapters.hf import safe_path
    for name in ['../outside','missions/..\\..\\outside.json','G:/outside.json']:
        with pytest.raises(ValueError):safe_path(root,name)
    with pytest.raises(ValueError):verify(root,['../outside'])

@pytest.fixture(scope='module')
def actual():
    root=os.environ.get('ASTRALOGUE_HF_SOURCE');source=os.environ.get('ASTRALOGUE_HSR_MAINLINE_SOURCE');packs=os.environ.get('ASTRALOGUE_HF_PACKS')
    if not root or not source or not packs:pytest.skip('Real pinned HF snapshot/source and built packs required')
    return Path(root),Path(source),Path(packs)

def test_actual_002_alignment_has_independent_fuzzy_anchor_proof(actual):
    root,source,packs=actual
    with __import__('astralogue.storypack',fromlist=['StoryPack']).StoryPack(packs/'hf-002.storypack') as pack:
        a=next(iter(pack.metadata['narrative']['hf_alignment'].values()))
        assert a['report']['total_entries']==119 and a['report']['dialogue_entries']==98
        b=a['bindings']['tree/91'];assert b['selected']==100020340 and b['basis']=='game_two_sided_context'
        assert b['independent_evidence']['left']['source']==100020339
        assert b['independent_evidence']['right']['target']==100020341
        assert a['report']['new_game_verified_relations']==0

def test_actual_two_tasks_same_pipeline_and_offline_runtime(actual,tmp_path,monkeypatch):
    import socket
    from astralogue.storypack import StoryPack
    from tools.verify_hf import run
    root,source,packs=actual
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**kw:pytest.fail('offline runtime network'))
    for stem,total,dialogues in [('002',119,98),('001',169,143)]:
        with StoryPack(packs/('hf-'+stem+'.storypack')) as pack:
            a=next(iter(pack.metadata['narrative']['hf_alignment'].values()))
            assert a['report']['total_entries']==total and a['report']['dialogue_entries']==dialogues
            for mid,mode in pack.metadata['narrative']['modes'].items():
                if mode.get('scope')!='hf_contiguous_excerpt':continue
                ids,rt,_=run(pack,mid,tmp_path/(stem+'-'+str(mode['hf_indices'][0])+'.save.json'))
                assert ids==[a['bindings']['tree/'+str(i)]['selected'] for i in mode['hf_indices']]
                assert all(not value['verified'] for eid,value in pack.metadata['narrative']['relations'].items() if eid.startswith(mid.removesuffix(':reader')))

def test_original_six_branches_survive_hf_merge(actual):
    from astralogue.storypack import StoryPack
    from astralogue.runtime import Runtime,ChoiceEvent,DialogueEvent,EndEvent,BlockedEvent
    root,source,packs=actual
    with StoryPack(packs/'hf-002.storypack') as pack:
        mid=next(k for k,v in pack.metadata['mission_labels'].items() if v.get('scope')=='SUBMISSION_FRAGMENT' and v.get('sub_id')=='100020113')
        for first in ['1','2']:
            for second in ['1','2','3']:
                rt=Runtime(pack,mid);choices=iter([first,second]);ids=[]
                for _ in range(100):
                    e=rt.next()
                    if isinstance(e,ChoiceEvent):rt.choose(next(choices))
                    elif isinstance(e,DialogueEvent):ids.append(pack.node(e.node).data['sentence_id'])
                    elif isinstance(e,EndEvent):break
                    elif isinstance(e,BlockedEvent):pytest.fail(str(e))
                else:pytest.fail('original fragment did not finish')
                assert (100020332 in ids)==(first=='1')
                assert (100020335 in ids)==(first=='2')
                assert (100020345 in ids)==(second=='3')
                assert 'hsr:finish:Mission_100020113' in rt.state.events

def test_typographic_tilde_is_normalized_without_rewriting_source(tiny):
    source,_,_=tiny
    mapping=load_json(source/'TextMap/TextMapCHS.json');mapping['7']='格式宽度～';write(source/'TextMap/TextMapCHS.json',mapping)
    rows=load_json(source/'ExcelOutput/TalkSentenceConfig.json');rows.append({'TalkSentenceID':7,'TalkSentenceText':{'Hash':7}});write(source/'ExcelOutput/TalkSentenceConfig.json',rows)
    match=DialogueIndex(source).match('格式宽度~')
    assert match['selected']==7 and match['basis']=='normalized_exact'
    assert match['candidates'][0]['text']=='格式宽度～'

def test_known_control_disagreement_splits_instead_of_inventing_path(tiny):
    from types import SimpleNamespace
    source,root,name=tiny
    raw=load_json(root/name);raw['story']=[raw['story'][0],{'type':'對話','speaker':'角色甲','content':'结构中文甲乙丁'}];write(root/name,raw)
    manifest=load_json(root/'source-manifest.json');manifest['files'][name]['sha256']=file_hash(root/name);write(root/'source-manifest.json',manifest)
    class Evidence:
        pack=SimpleNamespace(metadata={'pack_id':'test-pack'})
        def collect(self,title):return {'owned_ids':[1,4],'main_candidates':['10'],'option_groups':{},'pairs':[{'source':1,'target':3,'evidence':[{'entry':'control'}]}],'paths':[],'blocked':[],'truncated':False}
    a=align_dataset(root,name,source,DialogueIndex(source),Evidence())
    assert a['report']['potential_control_conflicts']==1 and a['segments']==[]

def test_control_identity_change_rejects_reader_build_before_modification(tiny,graph):
    source,_,_=tiny
    a={'control_pack_id':'old-pack','inputs':{}}
    before=deepcopy(graph.to_dict())
    with pytest.raises(ValueError,match='identity mismatch'):compile_dataset_reader(a,source,graph)
    assert graph.to_dict()==before

def test_reader_cli_cannot_access_dataset_or_upstream(actual,tmp_path):
    import subprocess,sys
    from astralogue.storypack import StoryPack
    from tools.verify_hf import run
    root,source,packs=actual;copy=tmp_path/'standalone.storypack';copy.write_bytes((packs/'hf-002.storypack').read_bytes())
    with StoryPack(copy) as pack:
        _,_,input_=run(pack,pack.metadata['narrative']['entries']['reader'],tmp_path/'seed.save.json')
    code="""import sys,os,runpy
pack,dataset,source,save=sys.argv[1:]
denied=[os.path.normcase(os.path.abspath(p)) for p in [dataset,source]]
def guard(event,args):
 if event=='socket.connect':raise AssertionError('Network forbidden')
 if event=='open' and isinstance(args[0],str):
  path=os.path.normcase(os.path.abspath(args[0]))
  if any(path==p or path.startswith(p+os.sep) for p in denied):raise AssertionError('Build input access forbidden')
sys.addaudithook(guard)
sys.argv=['astralogue','reader','play','--pack',pack,'--autosave',save]
runpy.run_module('astralogue',run_name='__main__')
"""
    result=subprocess.run([sys.executable,'-c',code,str(copy),str(root),str(source),str(tmp_path/'cli.save.json')],input=input_,text=True,encoding='utf8',capture_output=True,cwd=tmp_path,env={**os.environ,'PYTHONIOENCODING':'utf8'},timeout=30)
    assert result.returncode==0,result.stderr
    assert 'Reader 所选文字阅读段结束' in result.stdout
    assert 'Reader 范围' in result.stdout and '83–94' in result.stdout

def test_static_control_projection_never_skips_player_choice(graph):
    from types import SimpleNamespace
    from astralogue.hsr.hf_alignment import GameEvidence
    evidence=GameEvidence.__new__(GameEvidence);evidence.bundle=graph;evidence.refs={}
    for node in graph.nodes:
        if node.id in {'a','b','c','d'}:node.data['sentence_id']={'a':1,'b':2,'c':3,'d':4}[node.id]
    evidence.option_ids={('pick','first'):11,('pick','second'):12}
    evidence.pack=SimpleNamespace(edges=lambda nid:[e for e in graph.edges if e.source==nid],metadata={'pack_id':'structural'})
    pairs={(p['source'],p['target']) for p in evidence.static_pairs({'m'})}
    assert (1,11) in pairs and (1,12) in pairs
    assert (11,2) in pairs and (12,3) in pairs
    assert (1,2) not in pairs and (1,3) not in pairs
    assert (2,4) in pairs and (3,4) in pairs
