from astralogue.adapters.wiki.scenes import classify_page
from astralogue.audit.presentation import body


def page(text):
    return {'title':'test','page_id':1,'revision_id':2,'snapshot_sha256':'sha','wikitext':text,'choices':[],'stage_directions':[]}


def test_inspection_structure_preserves_first_and_repeat_without_assuming_optional():
    result=classify_page(page('===进入大厅===\n{{折叠|标题=调查装置|内容=第一次调查。<br>\n{{颜色|描述|再次调查}}<br>又调查一次。}}'))
    item=result['sections'][0]['interactions'][0]
    assert item['kind']=='unknown' and item['interaction_requirement']=='active_inspection'
    assert item['affects_mainline']=='unknown' and item['availability']=='unknown'
    assert [s['trigger'] for s in item['segments']]==['first_inspection','repeat_inspection']
    assert [s['text'] for s in item['segments']]==['第一次调查。','又调查一次。']
    assert '再次调查' in item['source']['raw']


def test_fold_alone_does_not_prove_optional_and_direction_is_not_repeat():
    result=classify_page(page('===任务===\n{{折叠|标题=场景|内容=一些文字}}\n{{折叠|标题=调查目标|内容={{颜色|描述|目标闪烁}}继续观察。}}'))
    generic,active=result['sections'][0]['interactions']
    assert generic['kind']=='unknown'
    assert len(active['segments'])==1
    assert active['repeat_policy']=='unknown'
    nested=classify_page(page('===任务===\n{{折叠|标题=调查装置|内容={{剧情选项|选项1=继续|剧情1={{颜色|描述|再次调查}}分支文字}}}}'))
    assert len(nested['sections'][0]['interactions'][0]['segments'])==1
    assert nested['sections'][0]['interactions'][0]['segments'][0]['unknown']


def test_repeat_preview_separates_visits():
    payload={'suggestion':{'after':{'segments':[{'trigger':'first_inspection','text':'首次正文'},{'trigger':'repeat_inspection','text':'重复正文'}]}}}
    rendered=body(payload)
    assert '首次主动调查时' in rendered and '再次主动调查时' in rendered
    assert '不能顺序自动播出' in rendered
