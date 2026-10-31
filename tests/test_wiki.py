import pytest
from astralogue.adapters.wiki import normalize,parse,review,report
from astralogue.model import digest

def test_unicode_quotes_without_destructive_case_folding():
    assert normalize(' A\u00a0 “B”  ')== 'A "B"'
    assert normalize('No')!=normalize('no')

def test_unverified_templates_block_instead_of_flattening():
    p=parse({'format':'wikitext','content':": '''Speaker:''' structural label\n{{Unknown|branch}}"})
    assert [n['type'] for n in p['tree']]==['dialogue','unknown']

def test_nested_choice_merge_remains_structural():
    tree=[{'type':'choice','options':[{'text':'a','body':[{'type':'choice','options':[{'text':'b','body':[]}]}]},{'text':'c','body':[]}]},{'type':'dialogue','text':'after'}]
    assert parse({'format':'wiki-tree-v1','tree':tree})['tree']==tree

def test_html_does_not_fake_supported_fandom_profile():
    assert parse({'format':'html','content':'<dl>unknown</dl>'})['tree'][0]['type']=='unknown'

def test_empty_choice_is_invalid():
    with pytest.raises(ValueError):parse({'format':'wiki-tree-v1','tree':[{'type':'choice','options':[]}]})

def test_stale_review_rejected():
    with pytest.raises(ValueError):review({'bindings':{}},{'alignment_hash':'stale','reviewer':'test','selections':{}})

def test_review_does_not_select_unknown_id():
    a={'bindings':{'tree/0':{'candidates':[{'id':1}],'selected':None}}}
    with pytest.raises(ValueError):review(a,{'alignment_hash':digest(a),'reviewer':'test','selections':{'tree/0':2}})
    out=review(a,{'alignment_hash':digest(a),'reviewer':'test','selections':{'tree/0':1}})
    assert out['bindings']['tree/0']['status']=='COMMUNITY_REVIEWED' and a['bindings']['tree/0']['selected'] is None

def test_real_english_catalog_roundtrip_is_not_wiki_completion(tmp_path):
    import os
    from pathlib import Path
    from astralogue.adapters.wiki import align,build
    from astralogue.model import load_json
    from astralogue.compiler import compile_story
    from astralogue.storypack import StoryPack
    from astralogue.runtime import Runtime,ChoiceEvent,DialogueEvent,EndEvent
    source=os.environ.get('ASTRALOGUE_HSR_MAINLINE_SOURCE');english=os.environ.get('ASTRALOGUE_HSR_EN')
    if not source or not english:pytest.skip('Pinned English snapshot required')
    source=Path(source);en=load_json(Path(english));chs=load_json(source/'TextMap/TextMapCHS.json')
    rows=load_json(source/'ExcelOutput/TalkSentenceConfig.json')
    row=next(r for r in rows if r.get('TalkSentenceID')==146010202);key=str(row['TalkSentenceText']['Hash'])
    p=parse({'format':'wiki-tree-v1','url':'local:catalog-roundtrip-not-wiki','revision_id':'structural-test','tree':[{'type':'dialogue','text':en[key]}]})
    a=align(p,source,english)
    assert 146010202 in [c['id'] for c in a['bindings']['tree/0']['candidates']]
    if a['bindings']['tree/0']['selected'] is None:
        a=review(a,{'alignment_hash':digest(a),'reviewer':'catalog structural test','selections':{'tree/0':146010202}})
    path=tmp_path/'aligned.storypack';compile_story(build(a,source),path)
    with StoryPack(path) as sp:
        rt=Runtime(sp,'wiki:reader');assert isinstance(rt.next(),ChoiceEvent);rt.choose('confirm')
        e=rt.next();assert isinstance(e,DialogueEvent) and e.text==chs[key]
        assert isinstance(rt.next(),EndEvent)
    assert report(a)['full_game_tasks_proven']==0
