from copy import deepcopy
from pathlib import Path
import os

import pytest

from astralogue.arcs.session import ArcSession, migrate_save
from astralogue.compiler import compile_story
from astralogue.model import Bundle, Node, Edge, Mission, load_json
from astralogue.player import PlayerProfile, ProfileEvent, render, validate_name
from astralogue.runtime import DialogueEvent, ChoiceEvent, EndEvent
from astralogue.storypack import StoryPack
from astralogue.adapters.hf import write


AVATARS = {'girl': {'name':'星','text_variant':'F'}, 'boy': {'name':'穹','text_variant':'M'}}


@pytest.fixture
def identity_pack(tmp_path):
    b=Bundle(metadata={'version':'test','narrative':{'relations':{}},'story_arcs':{'m':{}},
                       'player_reader':{'avatars':AVATARS}})
    b.text('default-title','小剧场');b.text('line','你好，{NICKNAME}。{M#他}{F#她}来了。');b.text('confirm','确认')
    b.missions=[Mission('m','default-title','identity')]
    b.nodes=[Node('identity','m','choice',data={'player_action':'initialize'}),Node('line','m','dialogue','line'),Node('end','m','end')]
    b.edges=[Edge('id-edge','identity','line','option','confirm',value='confirm'),Edge('line-edge','line','end')]
    p=tmp_path/'p.storypack';compile_story(b,p)
    with StoryPack(p) as pack:yield pack


def initialize(rt,avatar='girl',name='阿鸢'):
    for value in [avatar,'confirm',name,'confirm']:
        assert isinstance(rt.next(),ProfileEvent);rt.identity_input(value)


def test_identity_transaction_confirmation_and_snapshot_rewind(identity_pack,tmp_path):
    rt=ArcSession(identity_pack,'m');rt.identity_input('girl');rt.identity_input('back')
    assert rt.next().stage=='avatar' and rt.profile.avatar_id is None
    rt.identity_input('boy');rt.identity_input('confirm')
    for value in ['', '   ', '阿\x00鸢', '阿\n鸢', 'A\u202eB','x'*33]:
        before=rt.snapshot()
        with pytest.raises(ValueError):rt.identity_input(value)
        assert rt.snapshot()==before
    rt.identity_input('旧代号');rt.identity_input('back');rt.identity_input('穹之名');rt.identity_input('confirm')
    assert rt.profile.avatar_id=='boy' and rt.profile.name_confirmed
    with pytest.raises(ValueError):rt.identity_input('girl')
    event=rt.next();assert event.text=='你好，穹之名。他来了。'
    rt.save(tmp_path/'save.json');loaded=ArcSession.load(identity_pack,tmp_path/'save.json')
    assert loaded.profile==rt.profile and isinstance(loaded.next(),EndEvent)
    rt.back();assert not rt.profile.avatar_confirmed and rt.next().stage=='avatar'
    assert identity_pack.text('line','CHS')=='你好，{NICKNAME}。{M#他}{F#她}来了。'


def test_profiles_are_save_local_and_invalid_saved_identity_is_rejected(identity_pack,tmp_path):
    a=ArcSession(identity_pack,'m');b=ArcSession(identity_pack,'m')
    initialize(a,'girl','星之名');initialize(b,'boy','另一个名字')
    assert a.next().text=='你好，星之名。她来了。'
    assert b.next().text=='你好，另一个名字。他来了。'
    a.save(tmp_path/'a.json');saved=load_json(tmp_path/'a.json')
    saved['state']['variables']['player_profile']['avatar_id']='unknown'
    write(tmp_path/'bad.json',saved)
    with pytest.raises(ValueError,match='载体'):ArcSession.load(identity_pack,tmp_path/'bad.json')
    saved['state']['variables'].pop('player_profile');write(tmp_path/'legacy.json',saved)
    migrated=ArcSession.load(identity_pack,tmp_path/'legacy.json')
    assert migrated.next().migration and migrated.state.node=='end'
    initialize(migrated,'boy','补全名字');assert isinstance(migrated.next(),EndEvent)


def test_save_before_story_identity_event_does_not_initialize_early(identity_pack,tmp_path):
    rt=ArcSession(identity_pack,'m');rt.save(tmp_path/'early.json')
    loaded=ArcSession.load(identity_pack,tmp_path/'early.json')
    assert not loaded.profile_migration and loaded.profile.avatar_id is None


def test_cross_chapter_context_uses_explicit_continuation_and_snapshot_variables(identity_pack,tmp_path):
    rt=ArcSession(identity_pack,'m');initialize(rt)
    rt.set_story_variable('promise',{'kept':True});rt.next()
    continued=rt.continue_to(identity_pack,'m')
    assert continued.profile==rt.profile
    assert continued.state.variables['promise']=={'kept':True}
    continued.state.variables['promise']['kept']=False
    assert rt.state.variables['promise']['kept']
    continued.save(tmp_path/'next.json');loaded=ArcSession.load(identity_pack,tmp_path/'next.json')
    assert loaded.profile==rt.profile and loaded.migrations[0]['chapter_continuation']['previous_node']=='end'
    assert isinstance(loaded.next(),DialogueEvent)  # confirmed identity is reused, not selected again


def test_reviewed_text_parameter_patch_is_hash_bound_and_reader_only(identity_pack):
    from astralogue.narrative.patch import apply_patch,validate_patch
    from astralogue.model import digest
    b=identity_pack.bundle();info=b.metadata['narrative']
    info.update(game='test',game_version='test',source_hashes={'a':'hash'},modes={'m':{'mode':'reader'}},policies={})
    b.texts['line']['CHS']='我叫开拓者。'
    patch={'patch_version':1,'id':'name','status':'reviewed','review':{'reviewer':'source-review','reviewed_at':'2026-11-01','evidence':['e']},
           'game':'test','game_version':'test','source_hashes':{'a':'hash'},'evidence':[{'id':'e','uri':'local:test'}],
           'operations':[{'op':'text_parameter','source':'line','start':2,'end':5,'literal':'开拓者','parameter':'nickname',
                          'text_hash':digest('我叫开拓者。'),'evidence':['e']}]}
    assert validate_patch(b,patch)['valid']
    overlay=apply_patch(b,patch);assert overlay.texts==b.texts and overlay.edges==b.edges
    assert next(n for n in overlay.nodes if n.id=='line').data['text_parameters'][0]['patch']=='name'
    stale=deepcopy(patch);stale['operations'][0]['text_hash']='stale'
    assert not validate_patch(b,stale)['valid']
    pending=deepcopy(patch);pending['status']='pending';assert not validate_patch(b,pending)['valid']


def test_offset_annotations_do_not_globally_replace_titles_or_unknown_markers():
    p=PlayerProfile('girl','星','阿鸢',True,True)
    text='开拓者，我叫开拓者。{UNKNOWN}'
    a={'start':6,'end':9,'literal':'开拓者','parameter':'nickname'}
    value,issues=render(text,p,AVATARS,[a])
    assert value=='开拓者，我叫阿鸢。{UNKNOWN}' and issues==['unresolved_placeholder:{UNKNOWN}']
    assert render('开拓者',p,AVATARS)[0]=='开拓者'
    assert 'stale_text_annotation' in render('发生变化',p,AVATARS,[a])[1]


def test_bwiki_nested_parameters_merge_and_inline_media_are_structural():
    from astralogue.adapters.wiki.bwiki import templates,inline,dialogue_body
    raw='{{剧情选项|选项1=甲|剧情1=*角色：{{颜色|描述1|回应甲}}\n|选项2=乙|剧情2=}}\n*角色：共同后续'
    t=next(t for t in templates(raw) if t['name']=='剧情选项')
    assert t['params']['剧情2']=='' and raw[t['end']:].strip()=='*角色：共同后续'
    rows,errors=dialogue_body(t['params']['剧情1']);assert not errors and rows[0]['text']=='回应甲'
    media=inline('拿上这个{{图标|道具甲}}。{{黑幕|编辑注释}}')
    assert media['text']=='拿上这个。' and len(media['media'])==2
    assert all('递' not in m['display'] for m in media['media'])
    assert inline('{{选项图标|对话}}')['media']==[]
    assert inline('[[文件:物品.png|alt=道具甲]]')['media'][0]['description']=='道具甲'
    assert inline('[[文件:未知.png]]')['media'][0]['display'] is None


def test_normal_play_hides_provenance_and_debug_reveals_it(tmp_path):
    from typer.testing import CliRunner
    from astralogue.cli import app
    b=Bundle(metadata={'version':'test','narrative':{'modes':{'m':{'mode':'reader'}},'entries':{'reader':'m'}}})
    b.text('default-title','一段故事');b.text('speech','你好');b.text('speaker','社区转录·角色甲');b.text('option','再见')
    b.missions=[Mission('m','default-title','line')]
    b.nodes=[Node('line','m','dialogue','speech','speaker'),Node('pick','m','choice',data={'reader_action':'recorded_path','reader_message':'来源 COMMUNITY_TRANSCRIPT；转录只记录此发言/选项'}),Node('end','m','end')]
    b.edges=[Edge('next','line','pick'),Edge('pick-edge','pick','end','option','option',value='first')]
    path=tmp_path/'ui.storypack';compile_story(b,path)
    runner=CliRunner();common=['play','m','--pack',str(path),'--autosave',str(tmp_path/'auto.json')]
    normal=runner.invoke(app,common,input='\n1\n\n')
    assert normal.exit_code==0 and '【角色甲】' in normal.stdout and '本段阅读结束' in normal.stdout
    assert all(token not in normal.stdout for token in ['社区转录·','[Reader]','COMMUNITY_TRANSCRIPT','未证明原游戏'])
    for args in [common+['--debug'],['--debug']+common]:
        debug=runner.invoke(app,args,input='\n1\n\n')
        assert debug.exit_code==0 and '【社区转录·角色甲】' in debug.stdout and '[Reader]' in debug.stdout and 'COMMUNITY_TRANSCRIPT' in debug.stdout


@pytest.fixture
def player_arc():
    path=os.environ.get('ASTRALOGUE_PLAYER_PACK')
    if not path:pytest.skip('Real identity/BWIKI chapter pack required')
    with StoryPack(Path(path)) as pack:yield pack


@pytest.mark.parametrize('avatar,nickname',[('8002','阿鸢'),('8001','另一个穹')])
def test_real_entire_prologue_with_identity_and_names(player_arc,tmp_path,avatar,nickname):
    pack=player_arc;mid=next(iter(pack.metadata['story_arcs']));rt=ArcSession(pack,mid)
    entered=[];named=[];initialization_positions=[]
    for step in range(2000):
        event=rt.next();n=pack.node(event.node)
        if isinstance(event,ProfileEvent):
            initialization_positions.append(event.node)
            initialize(rt,avatar,nickname)
        elif isinstance(event,DialogueEvent):
            if n.data.get('arc_action')=='task_enter':entered.append(n.data['task'])
            if nickname in event.text:named.append(n.data.get('task'))
        elif isinstance(event,ChoiceEvent):
            values={o.value for o in event.options}
            preferred=n.data.get('recorded_value')
            rt.choose(preferred if preferred in values else n.data.get('continuation_value') or ('recorded' if 'recorded' in values else event.options[0].value))
        elif isinstance(event,EndEvent):break
        else:pytest.fail(str(event))
        if step==400:
            rt.save(tmp_path/'mid.json');rt=ArcSession.load(pack,tmp_path/'mid.json')
    else:pytest.fail('Whole chapter did not reach exit')
    assert entered==list(range(7)) and len(initialization_positions)==1
    assert initialization_positions[0].endswith('row:135:player-identity')
    assert set(named)==set(range(1,7)) and rt.profile.nickname==nickname


def test_real_kafka_branches_responses_and_shared_merge(player_arc):
    p=player_arc;mid=next(iter(p.metadata['story_arcs']));report=p.metadata['player_reader']['report']
    branches={b['hf_index']:b for b in report['branches'] if b['page']=='混乱行至深处'}
    wake=branches[153];assert wake['option_ids']==[100020113,100020115,100020118]
    expected={'1':[100020114],'2':[100020116,None],'3':[100020119,100020120]}
    for value,wanted in expected.items():
        rt=ArcSession(p,mid);rt.state.node=wake['node'];event=rt.next();assert len(event.options)==3
        rt.choose(value);ids=[]
        while rt.state.node!=wake['merge']:
            n=p.node(rt.state.node);assert isinstance(rt.next(),DialogueEvent);ids.append(n.data['sentence_id'])
        assert ids==wanted
        assert rt.traversal[0]['provenance']['evidence']['class']=='WIKI_ALIGNED'
    assert len(p.edges(branches[160]['node']))==len(p.edges(branches[167]['node']))==3
    assert sum(b['added_options'] for b in report['branches'] if b['page']=='漩涡止于中心')==3


def test_real_optional_inquiries_return_hide_selected_and_restore(player_arc,tmp_path):
    p=player_arc;mid=next(iter(p.metadata['story_arcs']))
    menus=[b for b in p.metadata['player_reader']['report']['branches'] if b.get('loop_recovered')]
    assert len(menus)==2
    for branch in menus:
        rt=ArcSession(p,mid);rt.state.node=branch['node'];e=rt.next()
        assert {o.value for o in e.options}=={'1','2','continue'}
        rt.choose('2')
        for _ in range(10):
            event=rt.next()
            if isinstance(event,ChoiceEvent):break
            assert isinstance(event,DialogueEvent)
        assert event.node==branch['node'] and {o.value for o in event.options}=={'1','continue'}
        assert any(p.node(row['source']).kind=='set' for row in rt.traversal)
        path=tmp_path/'inquiry.json';rt.save(path);restored=ArcSession.load(p,path)
        assert {o.value for o in restored.next().options}=={'1','continue'}
        restored.back();assert {o.value for o in restored.next().options}=={'1','2','continue'}
        restored.choose('continue');assert restored.state.node==branch['merge']


def test_waiting_extras_are_not_played_after_identity_confirmation(player_arc):
    mid=next(iter(player_arc.metadata['story_arcs']))
    menu=player_arc.metadata['player_reader']['report']['optional_idle']['node']
    rt=ArcSession(player_arc,mid);rt.state.node=menu
    event=rt.next()
    assert isinstance(event,DialogueEvent)
    assert player_arc.node(event.node).data['hf_index']==145
    assert rt.traversal[0]['value']=='skip'
    debug=ArcSession(player_arc,mid);debug.state.node=menu;debug.inspect_idle=True
    assert isinstance(debug.next(),ChoiceEvent)


def test_real_community_variable_layouts_do_not_select_ambiguous_ids(player_arc):
    report=player_arc.metadata['player_reader']['report']
    ambiguous=[a for a in report['annotations'] if len(a.get('candidate_ids',[]))>1]
    assert len(ambiguous)==2
    for a in ambiguous:
        n=player_arc.node(a['node'])
        assert a['id'] is None and a['variable_layout_verified'] and not a['dialogue_id_assigned']
        assert n.data.get('sentence_id') is None
        assert set(n.data['text_parameters'][0]['game_sentence_ids'])==set(a['candidate_ids'])
    assert len(report['annotations'])==29 and len(report['literal_title_retained'])==2
    # The actual arc, not only a synthetic fixture, supplies Patch v1 bindings.
    from astralogue.narrative.patch import validate_patch,apply_patch
    from astralogue.model import digest
    b=player_arc.bundle();info=b.metadata['narrative'];target=report['annotations'][0]['node']
    n=next(n for n in b.nodes if n.id==target);annotation=n.data.pop('text_parameters')[0]
    e=player_arc.edges(target)[0];text=player_arc.text(e.text,'CHS')
    patch={'patch_version':1,'id':'actual-variable-regression','status':'reviewed',
        'game':info['game'],'game_version':info['game_version'],'source_hashes':info['source_hashes'],
        'evidence':[{'id':'e','uri':'local:verified-parameter-layout'}],
        'review':{'reviewer':'automated source-bound regression','reviewed_at':'2026-11-01','evidence':['e']},
        'operations':[{'op':'text_parameter','source':target,'option':e.value,'parameter':'nickname',
            'start':annotation['start'],'end':annotation['end'],'literal':annotation['literal'],'text_hash':digest(text),'evidence':['e']}]}
    assert validate_patch(b,patch)['valid']
    applied=apply_patch(b,patch)
    assert next(n for n in applied.nodes if n.id==target).data['text_parameters'][0]['patch']==patch['id']


def test_old_pack_save_requires_explicit_migration_and_preserves_progress(player_arc,tmp_path):
    value=os.environ.get('ASTRALOGUE_ARC_PACK')
    if not value:pytest.skip('M9 pack required')
    with StoryPack(Path(value)) as old:
        mid=next(iter(old.metadata['story_arcs']));rt=ArcSession(old,mid)
        for _ in range(300):
            e=rt.next()
            if isinstance(e,ChoiceEvent):rt.choose(old.node(e.node).data.get('recorded_value') or ('recorded' if any(o.value=='recorded' for o in e.options) else e.options[0].value))
        path=tmp_path/'old.json';rt.save(path);before=path.read_bytes()
        assert ArcSession.load(old,path).profile_notice
        with pytest.raises(ValueError,match='迁移'):ArcSession.load(player_arc,path)
        new=migrate_save(old,player_arc,path,tmp_path/'new.json')
        assert new.state.node==rt.state.node and path.read_bytes()==before
        assert new.migrations[0]['choices']==rt.state.choices
        assert new.migrations[0]['traversal']==rt.traversal
        initialize(new,'8001','迁移代号');new.save(tmp_path/'new.json')
        restored=ArcSession.load(player_arc,tmp_path/'new.json')
        assert restored.state.node==rt.state.node and restored.profile.nickname=='迁移代号'
        for _ in range(1500):
            event=restored.next()
            if isinstance(event,EndEvent):break
            if isinstance(event,ChoiceEvent):
                node=player_arc.node(event.node);values={o.value for o in event.options};preferred=node.data.get('recorded_value')
                restored.choose(preferred if preferred in values else node.data.get('continuation_value') or ('recorded' if 'recorded' in values else event.options[0].value))
            else:assert isinstance(event,DialogueEvent)
        else:pytest.fail('Migrated M9 save did not reach chapter exit')
