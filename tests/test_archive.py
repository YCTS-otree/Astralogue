from pathlib import Path
from typer.testing import CliRunner
from astralogue.archive import Archive,build
from astralogue.cli import app
import os,pytest

def test_real_archive_rebuild_search_and_offline(tmp_path):
    source=os.environ.get('ASTRALOGUE_HSR_MAINLINE_SOURCE')
    if not source:pytest.skip('real source required')
    source=Path(source); db=tmp_path/'a.sqlite'
    first=build(source,[],db)
    assert first==build(source,[],db,True)
    with Archive(db) as a:
        found=a.search('翁法罗斯',limit=2)
        assert found and len(found)<=2
        assert a.search(search=found[0]['id'])[0]['id']==found[0]['id']
        assert a.detail(found[0]['id'])['knowledge_type']=='character_statement_not_verified_world_fact'
        assert a.coverage()['full_missions_proven']==0
    result=CliRunner().invoke(app,['browse','--database',str(db),'--search','翁法罗斯'],input='n\np\nq\n')
    assert result.exit_code==0,result.output
    assert '非已验证剧情发生顺序' in result.output
    # Browsing reads only the copied database, not original build inputs.
    copied=tmp_path/'standalone.sqlite';copied.write_bytes(db.read_bytes());db.unlink()
    with Archive(copied) as a:assert a.search('翁法罗斯')

@pytest.fixture
def structural_source(tmp_path):
    import json
    root=tmp_path/'source'
    values={'source.json':{'revision':'test','game_version':'test'},'ExcelOutput/MainMission.json':[{'MainMissionID':10,'Type':'Main','Name':{'Hash':3}}], 'ExcelOutput/MissionChapterConfig.json':[], 'ExcelOutput/TalkSentenceConfig.json':[{'TalkSentenceID':1,'TalkSentenceText':{'Hash':2}},{'TalkSentenceID':2,'TalkSentenceText':{'Hash':2}}], 'TextMap/TextMapCHS.json':{'2':'结构测试中文','3':'任务结构'},'Config/Level/Mission/10/MissionInfo_10.json':{'MainMissionID':10,'SubMissionList':[{'ID':11,'MainMissionID':10,'MissionJsonPath':'Story/a.json'}]},'Story/a.json':{'TalkSentenceID':1}}
    for name,value in values.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf8')
    return root

def test_archive_ids_not_collapsed_by_identical_text(structural_source,tmp_path):
    db=tmp_path/'a.sqlite';build(structural_source,[],db)
    with Archive(db) as a:
        assert len(a.search('中文'))==2
        assert a.coverage()['mission_assigned']==1
        assert a.search(mission='10')[0]['id']=='1'
        assert a.search(category='TRAILBLAZE')[0]['id']=='1'
        assert a.search(orphans=True)
        assert a.detail('2')['occurrences']==[]

def test_archive_rebuild_requires_explicit_force(structural_source,tmp_path):
    db=tmp_path/'a.sqlite';build(structural_source,[],db)
    with pytest.raises(ValueError):build(structural_source,[],db)

def test_duplicate_pack_import_retains_one_instance(structural_source,tmp_path):
    from astralogue.model import Bundle,Node,Mission,Edge
    from astralogue.compiler import compile_story
    b=Bundle(metadata={'source':{'revision':'test'}});b.text('default-title','结构');b.text('title','结构');b.text('line','结构测试中文');b.missions=[Mission('m','title','d')];b.nodes=[Node('d','m','dialogue','line',data={'talk_sentence_id':1}),Node('end','m','end')];b.edges=[Edge('next','d','end')]
    p=tmp_path/'a.storypack';compile_story(b,p)
    db=tmp_path/'a.sqlite';r=build(structural_source,[p,p],db)
    assert r['graph_instances']==1
    assert r['verified_relations']==0
    with Archive(db) as a:assert a.tasks()[0]['status']=='needs_review'
