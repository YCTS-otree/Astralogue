"""Structural tests use observed HSR fields; real content is tested separately."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from astralogue.cli import app
from astralogue.compiler import compile_story
from astralogue.compiler.hsr_mainline import MainlineCompiler
from astralogue.hsr.fusion import supplement_texts
from astralogue.hsr.local import inspect_install
from astralogue.hsr.manifest import create_manifest
from astralogue.hsr.report import coverage
from astralogue.hsr.sources import ResourceError, Sources
from astralogue.model import Bundle
from astralogue.runtime import BlockedEvent, ChoiceEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack
from astralogue.hsr.download import PublicSnapshot
import hashlib


def task(kind, **kw): return {"$type": "RPG.GameCore." + kind, **kw}
def graph(*sequences): return {"OnInitSequece": [], "OnStartSequece": [{"TaskList": s} for s in sequences]}
def talk(sid): return task("PlayAndWaitSimpleTalk", SimpleTalkList=[{"TalkSentenceID": sid}])
def wait(event): return task("WaitCustomString", CustomString={"Value": event})
def emit(event): return task("TriggerCustomString", CustomString={"Value": event})


@pytest.fixture
def raw_mainline(tmp_path):
    root = tmp_path / "raw"
    def write(rel, obj):
        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")
    write("source.json", {"revision": "fixture-v1", "game_version": "fixture"})
    write("ExcelOutput/MainMission.json", [
        {"MainMissionID": 10, "Type": "Main", "ChapterID": 1, "WorldID": 101, "Name": {"Hash": 1}, "NextMainMissionList": [11], "TakeParam": [{"Type": "Auto"}]},
        {"MainMissionID": 11, "Type": "Companion", "Name": {"Hash": 1}},
        {"MainMissionID": 7, "Type": "Gap", "Name": {"Hash": 1}},
        {"MainMissionID": 1000101, "Type": "Branch", "Name": {"Hash": 1}}])
    write("ExcelOutput/MainMissionType.json", [{"Type": "Main", "TypeName": {"Hash": 2}}])
    write("ExcelOutput/MissionChapterConfig.json", [{"ID": 1, "ChapterName": {"Hash": 2}}])
    write("TextMap/TextMapCHS.json", {str(n): "structural-" + str(n) for n in range(1, 120)})
    write("ExcelOutput/TalkSentenceConfig.json", [{"TalkSentenceID": i, "TalkSentenceText": {"Hash": i}, "TextmapTalkSentenceName": {"Hash": 2}} for i in range(101, 110)])
    write("ExcelOutput/PerformanceD.json", [{"PerformanceID": 77, "PerformancePath": "Config/Level/Mission/10/Act/branch.json"}])
    write("Config/Level/Mission/10/MissionInfo_10.json", {"MainMissionID": 10, "StartSubMissionList": [100], "FinishSubMissionList": [101]})
    subs = []
    for sid in [100, 101]:
        subs.append({"ID": sid, "MainMissionID": 10, "MissionJsonPath": f"Config/Level/Mission/10/Mission_{sid}.json",
                     "TakeType": "Auto" if sid == 100 else "AnySequence", "TakeParamIntList": [] if sid == 100 else [100],
                     "FinishType": "Talk", "ParamType": "Equal", "ParamStr1": f"finish{sid}", "Progress": 1, "FinishActionList": []})
    write("Config/Level/Mission/10/MissionInfo_10.partial.json", {"SubMissionList": subs})
    write("Config/Level/Mission/10/Mission_100.json", graph([task("TriggerPerformance", PerformanceType="D", PerformanceID=77, ValueSource={}), task("FinishPerformanceMission", Key="finish100")]))
    write("Config/Level/Mission/10/Mission_101.json", graph([talk(107), task("FinishPerformanceMission", Key="finish101")]))
    scene = graph(
        [talk(101), task("PlayOptionTalk", OptionList=[{"TalkSentenceID": 102, "TriggerCustomString": "a"}, {"TalkSentenceID": 103, "TriggerCustomString": "b"}])],
        [wait("a"), talk(104), emit("merge")], [wait("b"), talk(105), emit("merge")],
        [wait("merge"), talk(106), task("EndPerformance")])
    write("Config/Level/Mission/10/Act/branch.json", scene)
    return root, write, scene


def make_pack(root, out):
    compiler = MainlineCompiler(root)
    b = compiler.compile()
    compile_story(b, out)
    return b


def run_to_end(rt, selection="1"):
    lines = []
    for _ in range(200):
        event = rt.next()
        if isinstance(event, DialogueEvent): lines.append(rt.pack.node(event.node).data["sentence_id"])
        elif isinstance(event, ChoiceEvent): rt.choose(selection)
        elif isinstance(event, EndEvent): return lines
        elif isinstance(event, BlockedEvent): pytest.fail(str(event))
    pytest.fail("step limit")


def test_classification_from_fields_not_ids(raw_mainline):
    root, _, _ = raw_mainline
    ms = {m["id"]: m for m in create_manifest(root)["missions"]}
    assert ms["10"]["category"] == "TRAILBLAZE"
    assert ms["7"]["category"] == "CONTINUANCE"
    assert ms["11"]["category"] == "COMPANION"
    assert ms["1000101"]["category"] == "ADVENTURE"
    assert ms["10"]["next_declared"] == [11]
    assert ms["10"]["entries"] == ["100"]
    assert not ms["10"]["classification"]["inferred"]


@pytest.mark.parametrize("choice,line", [("1", 104), ("2", 105)])
def test_actual_entry_call_return_subgoals_and_end(raw_mainline, tmp_path, choice, line):
    root, _, _ = raw_mainline; out = tmp_path / "main.storypack"; make_pack(root, out)
    with StoryPack(out) as pack:
        rt = Runtime(pack, "hsr:mission:10")
        assert run_to_end(rt, choice) == [101, line, 106, 107]
        assert not rt.state.frames
        assert rt.state.variables["hsr:sub:100:finished"] is True
        assert rt.state.variables["hsr:sub:101:finished"] is True
        assert {"hsr:finish:finish100", "hsr:finish:finish101"} <= set(rt.state.events)


def test_call_stack_save_restore_and_back(raw_mainline, tmp_path):
    root, _, _ = raw_mainline; out = tmp_path / "main.storypack"; make_pack(root, out)
    save = tmp_path / "save.json"
    with StoryPack(out) as p:
        rt = Runtime(p, "hsr:mission:10")
        assert rt.next().node
        event = rt.next(); assert isinstance(event, ChoiceEvent)
        assert len(rt.state.frames) == 2
        rt.choose("1"); assert rt.next().text
        rt.save(save)
    with StoryPack(out) as p:
        rt = Runtime.load(p, save)
        assert len(rt.state.frames) == 2
        rt.back(); assert isinstance(rt.next(), ChoiceEvent)
        assert run_to_end(rt, "2") == [105, 106, 107]


def test_timeline_readable_control_graph(raw_mainline, tmp_path):
    root, write, scene = raw_mainline
    write("Config/Level/Mission/10/Act/branch.json", graph([task("PlayTimeline", TimelineName="logical.playable", Type="Story"), task("EndPerformance")]))
    write("timeline-index.json", {"logical.playable": "Timeline/readable.json"})
    write("Timeline/readable.json", scene)
    out = tmp_path / "timeline.storypack"; b = make_pack(root, out)
    refs = b.metadata["hsr_metrics"]["hsr:mission:10"]["timeline_references"]
    assert refs == [{"name": "logical.playable", "resolved": True}]
    with StoryPack(out) as p: assert run_to_end(Runtime(p, "hsr:mission:10")) == [101, 104, 106, 107]


def test_timeline_events_and_state_mutation(raw_mainline, tmp_path):
    root, write, _ = raw_mainline
    write("Config/Level/Mission/10/Mission_101.json", graph([
        task("PredicateTaskList", Predicate={"$type": "RPG.GameCore.ByCompareSubMissionState", "SubMissionID": 100, "SubMissionState": "Finish"},
             SuccessTaskList=[task("SetMissionCustomValue", SubmissionID=101, MissionCustomValue={"Name": "flag", "ValidValueParamList": [0, 1]}, CustomValue=1), talk(107)],
             FailedTaskList=[talk(108)]), task("FinishPerformanceMission", Key="finish101")]))
    out = tmp_path / "state.storypack"; make_pack(root, out)
    with StoryPack(out) as p:
        rt = Runtime(p, "hsr:mission:10")
        assert run_to_end(rt) == [101, 104, 106, 107]
        assert rt.state.variables["hsr:custom:101:flag"] == 1


def test_missing_timeline_preserves_reference_and_blocks(raw_mainline, tmp_path):
    root, write, _ = raw_mainline
    write("Config/Level/Mission/10/Act/branch.json", graph([task("PlayTimeline", TimelineName="missing.playable", Type="Story"), task("EndPerformance")]))
    out = tmp_path / "missing.storypack"; b = make_pack(root, out)
    assert b.metadata["hsr_metrics"]["hsr:mission:10"]["timeline_references"][0]["resolved"] is False
    with StoryPack(out) as p:
        assert isinstance(Runtime(p, "hsr:mission:10").next(), BlockedEvent)
        r = coverage(p)
        assert r["timeline_control_container_references"]["resolved"] == 0
        assert r["summary"]["runtime_complete_with_dialogue"] == 0
        assert any(x["path"] == "missing.playable" for x in r["missing_resources"])


def test_coverage_separates_fragments_and_tasks(raw_mainline, tmp_path):
    root, _, _ = raw_mainline; out = tmp_path / "main.storypack"; make_pack(root, out)
    with StoryPack(out) as p:
        r = coverage(p)
        assert r["summary"]["identified"] == 1
        assert r["summary"]["runtime_complete_with_dialogue"] == 1
        assert r["summary"]["all_known_branches_complete"] == 1
        assert r["fragments"]
        assert coverage(p, max_states=1)["summary"]["runtime_complete_with_dialogue"] == 0


def test_conflicting_performance_is_not_selected(raw_mainline, tmp_path):
    root, write, _ = raw_mainline
    write("ExcelOutput/PerformanceDS.json", [{"PerformanceID": 77, "PerformancePath": "Story/other.json"}])
    out = tmp_path / "conflict.storypack"; make_pack(root, out)
    with StoryPack(out) as p: assert isinstance(Runtime(p, "hsr:mission:10").next(), BlockedEvent)


def test_supplement_version_conflict_and_content_conflict(raw_mainline, tmp_path):
    root, _, _ = raw_mainline
    other = tmp_path / "other"; other.mkdir()
    (other / "source.json").write_text('{"revision":"different","game_version":"different"}')
    (other / "new.json").write_text('{"OnStartSequece":[]}')
    sources = Sources([root, other])
    with pytest.raises(ResourceError, match="版本"): sources.read("new.json")
    (other / "ExcelOutput").mkdir()
    (other / "ExcelOutput/PerformanceD.json").write_text("[]")
    with pytest.raises(ResourceError, match="冲突"): Sources([root, other]).read("ExcelOutput/PerformanceD.json")


def test_path_escape_and_encrypted_input_rejected(raw_mainline):
    root, _, _ = raw_mainline; sources = Sources([root])
    with pytest.raises(ResourceError): sources.read("../outside.json")
    (root / "locked.playable").write_bytes(b"ENCR" + bytes(40))
    before = (root / "locked.playable").read_bytes()
    with pytest.raises(ResourceError, match="不解密"): sources.timeline("locked.playable")
    assert (root / "locked.playable").read_bytes() == before


def test_overlay_does_not_overwrite_text_or_connect_control(raw_mainline):
    root, _, _ = raw_mainline
    b = MainlineCompiler(root).compile()
    candidate = Bundle(metadata={"source": {"game_version": "other"}})
    candidate.text("hsr:text:101", "conflict")
    original_edges = len(b.edges)
    supplement_texts(b, candidate, "third-party")
    assert b.texts["hsr:text:101"]["CHS"] == "structural-101"
    assert len(b.edges) == original_edges
    assert b.metadata["source_conflicts"]
    assert any(n.kind == "unknown" and n.data.get("operation") == "source_text_conflict" for n in b.nodes)


def test_install_inventory_is_read_only(tmp_path):
    game = tmp_path / "game"; game.mkdir(); (game / "StarRail.exe").write_bytes(b"MZ")
    (game / "config.ini").write_text("[General]\ngame_version=4.6.0\n")
    folder = game / "StarRail_Data/StreamingAssets/Asb/Windows"; folder.mkdir(parents=True)
    block = folder / "sample.block"; block.write_bytes(b"ENCR" + bytes(64))
    before = {p: p.read_bytes() for p in game.rglob("*") if p.is_file()}
    result = inspect_install(game)
    assert result["read_only"] and result["game_version"] == "4.6.0"
    assert next(iter(result["categories"].values()))["sampled_headers"][0]["format"] == "ENCR"
    assert before == {p: p.read_bytes() for p in game.rglob("*") if p.is_file()}


def test_hsr_cli_pipeline(raw_mainline, tmp_path):
    root, _, _ = raw_mainline; runner = CliRunner()
    ir, out, report = tmp_path / "main.json", tmp_path / "main.storypack", tmp_path / "coverage.json"
    assert runner.invoke(app, ["hsr", "import-mainline", "--source", str(root), "--output", str(ir)]).exit_code == 0
    assert runner.invoke(app, ["build", "--source", str(ir), "--output", str(out)]).exit_code == 0
    result = runner.invoke(app, ["hsr", "coverage", "--pack", str(out), "--report", str(report)])
    assert result.exit_code == 0, result.output
    assert json.loads(report.read_text(encoding="utf-8"))["summary"]["identified"] == 1
    listed = runner.invoke(app, ["hsr", "list", "--pack", str(out), "--json-output"])
    assert len(json.loads(listed.output)) == 1


def test_download_checks_git_blob_without_overwriting(raw_mainline):
    root, _, _ = raw_mainline
    rel = "ExcelOutput/PerformanceD.json"; path = root / rel
    data = path.read_bytes()
    sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    snapshot = PublicSnapshot(root, None); snapshot.index[rel] = {"sha": sha}
    assert snapshot.fetch(rel) == (rel, None)
    path.write_text("[]")
    assert "mismatch" in snapshot.fetch(rel)[1]
    assert path.read_text() == "[]"


def test_unknown_nested_control_is_not_cosmetic(raw_mainline):
    root, write, scene = raw_mainline
    scene["OnStartSequece"][0]["TaskList"].insert(0, task("PerformanceTransition", OnComplete=[emit("a")]))
    write("Config/Level/Mission/10/Act/branch.json", scene)
    bundle = MainlineCompiler(root).compile()
    assert any(n.kind == "unknown" and n.data.get("raw", {}).get("$type", "").endswith("PerformanceTransition") for n in bundle.nodes if isinstance(n.data.get("raw"), dict))


def test_blocked_dynamic_call_still_preserves_literal_callee_text(raw_mainline, tmp_path):
    root, write, _ = raw_mainline
    write("Config/Level/Mission/10/Mission_100.json", graph([
        task("TriggerPerformance", PerformanceType="D", PerformanceID=77, ValueSource={"dynamic": True}),
        task("FinishPerformanceMission", Key="finish100")]))
    out = tmp_path / "dynamic.storypack"; b = make_pack(root, out)
    assert b.texts["hsr:text:104"]["CHS"] == "structural-104"
    assert b.metadata["hsr_metrics"]["hsr:mission:10"]["option_references"] == 2
    with StoryPack(out) as p: assert isinstance(Runtime(p, "hsr:mission:10").next(), BlockedEvent)


def test_mainline_returns_to_menu_after_completion(raw_mainline, tmp_path, monkeypatch):
    root, _, _ = raw_mainline; out = tmp_path / "menu.storypack"; make_pack(root, out)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["hsr", "play", "--pack", str(out)], input="1\n\n1\n\n\n\n\nq\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("选择会话编号") == 2
    assert "本会话结束" in result.output


def test_verified_sqlite_hash_can_fill_missing_text_without_flow_override(raw_mainline, tmp_path):
    root, _, _ = raw_mainline
    bundle = MainlineCompiler(root).compile()
    del bundle.texts["hsr:text:104"]["CHS"]
    overlay = Bundle(metadata={"adapter": "browser-sqlite", "source": {"revision": "fixture-v1", "game_version": "fixture"}})
    overlay.text("export:text:104", "structural-104")
    original_edges = len(bundle.edges)
    supplement_texts(bundle, overlay, "verified-sqlite")
    assert bundle.texts["hsr:text:104"]["CHS"] == "structural-104"
    assert len(bundle.edges) == original_edges
    path = tmp_path / "fused.storypack"; compile_story(bundle, path)
    with StoryPack(path) as pack: assert coverage(pack)["dialogue_references"]["ratio"] == 1.0


def test_timeline_index_cannot_override_another_revision(raw_mainline, tmp_path):
    root, write, scene = raw_mainline
    write("Timeline/a.json", scene)
    write("timeline-index.json", {"scene.playable": "Timeline/a.json"})
    extra = tmp_path / "extra"; extra.mkdir()
    (extra / "source.json").write_text('{"revision":"other"}')
    (extra / "timeline-index.json").write_text('{"scene.playable":"Timeline/a.json"}')
    with pytest.raises(ResourceError, match="索引版本"): Sources([root, extra]).timeline("scene.playable")
