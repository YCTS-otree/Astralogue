"""Separate identity coverage, source provenance, novelty and execution reports."""
from pathlib import Path
from collections import Counter
from astralogue.model import load_json,digest,file_hash
from astralogue.adapters.hf import verify,write,SAMPLES
from astralogue.hsr.hf_alignment import GameEvidence,previous_reader_pairs,ALIGNER_VERSION
from astralogue.storypack import StoryPack

root=Path('data/external/hf-trailblaze');manifest=verify(root);paths=sorted(Path('data/staging/hf-aligned').glob('*.json'))
all_docs=[load_json(p) for p in paths if p.name!='batch-report.json' and not p.name.endswith('.failed.json')]
assert all(a.get('hf_alignment_version')==1 for a in all_docs)
unique={a['inputs']['hf']:a for a in all_docs}
prior_reader=previous_reader_pairs([Path('data/packs/hsr-reader.storypack'),Path('data/packs/hsr-mainline-reader.storypack')])
with StoryPack(Path('data/packs/hsr-mainline-m59.storypack')) as p:
    game=GameEvidence(p,Path('data/raw/hsr-mainline'))
    static={(r['source'],r['target']) for r in game.static_pairs({m.id for m in game.bundle.missions})}
    context={'pack_id':p.metadata['pack_id'],'chs':file_hash(Path('data/raw/hsr-mainline/TextMap/TextMapCHS.json')),'sentences':file_hash(Path('data/raw/hsr-mainline/ExcelOutput/TalkSentenceConfig.json')),'parser':ALIGNER_VERSION}
    all_docs=[a for a in all_docs if a.get('cache_key')==digest([context,a['inputs']['hf']]) and manifest['files'].get(a['report']['file'],{}).get('sha256')==a['inputs']['hf']]
    unique={a['inputs']['hf']:a for a in all_docs}
prior_runtime={tuple(pair) for a in all_docs for pair in a['game_evidence'].get('runtime_pair_ids',[])}
baseline=prior_reader|static|prior_runtime
prior_ids={sid for pair in prior_reader for sid in pair}|{sid for a in all_docs for sid in a['game_evidence'].get('runtime_reached_ids',[])}
runtime=load_json(Path('data/m8-hf-runtime.json'))
samples=[];all_new=set();reader_ids=set();selected_ids=set()
for name in SAMPLES:
    a=next(a for a in all_docs if a['report']['file']==name);stem=Path(name).name[:3];build=load_json(Path('data/packs')/('hf-'+stem+'.build.json'))
    actual=next(r for r in runtime['samples'] if r['report']['file']==name)
    hf={(r['source_id'],r['target_id']) for r in a['relations'] if r['status']=='HF_ORDER_ONLY'}
    newly=hf-baseline;all_new|=newly
    rids={sid for run in actual['runs'] for sid in run['ids']};reader_ids|=rids
    sids={b['selected'] for b in a['bindings'].values() if b['selected'] is not None};selected_ids|=sids
    extra={'unique_exact_accepted':sum(b['selected'] is not None and b['exact_count']==1 for b in a['bindings'].values()),'multiple_exact_resolved':sum(b['selected'] is not None and b['exact_count']>1 for b in a['bindings'].values()),'new_hf_external_pairs':len(newly),'new_game_verified_pairs':0,'runtime_completed_excerpts':actual['runtime_completed_excerpts'],'reader_distinct_ids':len(rids),'new_reader_ids_over_known_reachable_baseline':len(rids-prior_ids),'matching_coverage':a['report']['selected_ids']/a['report']['dialogue_entries'],'overall_accuracy':'not_estimated','default_cli':actual['default_cli'],'novel_cli':actual.get('novel_cli'),'pack_id':actual['pack_id'],'strict_graph_preserved':build['strict_graph_preserved'],'runtime_observed_cross_relations':sum(r['status']=='GAME_CROSS_CONFIRMED' for r in a['relations']),'static_cross_relations':sum(r['status']=='GAME_STATIC_CROSS_CONFIRMED' for r in a['relations'])}
    samples.append({**a['report'],**extra,'runtime':'verified bounded excerpts','new_hf_external_pair_inventory':sorted(newly)})
keys=['total_entries','dialogue_entries','unique_raw_exact','unique_normalized_exact','multiple_exact','selected_ids','fuzzy_candidate_entries','independently_confirmed_fuzzy','completely_unmatched','cross_confirmed_relations','hf_only_relations','potential_control_conflicts']
batch={'files':len(all_docs),'unique_content_documents':len(unique),'raw_file_sum':{k:sum(a['report'][k] for a in all_docs) for k in keys},'deduplicated_content_sum':{k:sum(a['report'][k] for a in unique.values()) for k in keys},'selected_distinct_ids':len({b['selected'] for a in all_docs for b in a['bindings'].values() if b['selected'] is not None}),'distinct_hf_candidate_pairs':len({(r['source_id'],r['target_id']) for a in all_docs for r in a['relations'] if r['status']=='HF_ORDER_ONLY'}),'runtime_tested_files':2,'compiled_files':2,'full_game_tasks_proven':0,'batch_candidates_are_not_execution_proofs':True,'bounded_evidence_truncated_files':[a['report']['file'] for a in all_docs if a['game_evidence']['truncated']]}
result={'aligner_version':ALIGNER_VERSION,'repository':manifest['repository'],'revision':manifest['revision'],'samples':samples,'novelty':{'unit':'distinct ordered TalkSentenceID pairs, not all contextual occurrences','baseline_reader_pairs':len(prior_reader),'baseline_static_game_pairs':len(static),'baseline_runtime_pairs':len(prior_runtime),'new_hf_external_pairs_two_samples':len(all_new),'new_game_verified_pairs':0,'selected_distinct_ids_two_samples':len(selected_ids),'reader_distinct_ids_two_samples':len(reader_ids),'new_reader_ids_vs_known_baseline':len(reader_ids-prior_ids),'baseline_scope':'bounded existing M5 controls and M6 Reader profiles; not all possible game states'},'batch':batch,'targeted_review':load_json(Path('data/hf-source-review.json')),'full_hf_task_ranges_completed':0,'full_native_game_tasks_completed':0}
write(Path('data/m8-hf-report.json'),result)
print({'new_hf_external_pairs':len(all_new),'selected_distinct_ids':len(selected_ids),'reader_distinct_ids':len(reader_ids),'new_reader_ids_over_measured_baseline':len(reader_ids-prior_ids),'unique_batch_documents':len(unique)})
