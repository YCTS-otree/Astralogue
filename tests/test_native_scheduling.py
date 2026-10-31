import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from astralogue.compiler import compile_story
from astralogue.compiler.schedule import ScheduledAction, compile_schedule
from astralogue.hsr.animestudio import write_json, normalize_resource
from astralogue.hsr.native_index import NativeIndex
from astralogue.hsr.native_scan import scan, target_report
from astralogue.hsr.native_scheduler import build
from astralogue.model import Bundle, Node, Edge, Mission, file_hash
from astralogue.runtime import Runtime, DialogueEvent, BlockedEvent, EndEvent
from astralogue.storypack import StoryPack


def scheduled_pack(tmp_path, actions, end_verified=True):
    b = Bundle(); b.text("default-title", "Schedule test"); b.text("title", "Schedule test")
    b.text("line", "Structural scheduler fixture")
    b.missions.append(Mission("m", "title", "caller"))
    entry, ret = compile_schedule(b, "m", "timeline", actions, 10, end_verified=end_verified)
    b.nodes.extend([Node("caller", "m", "call"), Node("done", "m", "end")])
    b.edges.extend([Edge("call", "caller", entry, "call"), Edge("continuation", "caller", "done")])
    if ret: b.edges.append(Edge("return", ret, "done", "return"))
    path = tmp_path / "schedule.storypack"; compile_story(b, path)
    return path, b.metadata["logical_clocks"]["timeline"]


def test_generic_wait_freezes_clock_save_resume_and_return(tmp_path):
    actions = [ScheduledAction("a", 1, "dialogue", text="line"),
               ScheduledAction("wait", 2, "wait", {"event": "explicit-resume", "consume": True}),
               ScheduledAction("b", 3, "dialogue", text="line")]
    path, clock = scheduled_pack(tmp_path, actions)
    save = tmp_path / "save.json"
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), DialogueEvent)
        assert rt.state.variables[clock] == 1
        assert isinstance(rt.next(), BlockedEvent) and rt.state.variables[clock] == 2
        assert len(rt.state.frames) == 1; rt.save(save)
    with StoryPack(path) as pack:
        rt = Runtime.load(pack, save)
        assert isinstance(rt.next(), BlockedEvent) and rt.state.variables[clock] == 2
        rt.signal("explicit-resume")
        assert isinstance(rt.next(), DialogueEvent) and rt.state.variables[clock] == 3
        assert isinstance(rt.next(), EndEvent) and rt.state.variables[clock] == 10
        assert not rt.state.frames and "explicit-resume" not in rt.state.events


def test_same_time_requires_explicit_dependencies(tmp_path):
    actions = [ScheduledAction("second", 2, "emit", {"event": "b"}, after=("first",)),
               ScheduledAction("first", 2, "emit", {"event": "a"})]
    path, _ = scheduled_pack(tmp_path, actions)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), EndEvent)
        assert rt.state.events == ["a", "b"]


def test_same_time_ambiguous_actions_do_not_sort_ids(tmp_path):
    path, clock = scheduled_pack(tmp_path, [ScheduledAction("z", 2, "dialogue", text="line"), ScheduledAction("a", 2, "dialogue", text="line")])
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), BlockedEvent)
        assert rt.state.variables[clock] == 2
        assert pack.node(rt.state.node).data["operation"] == "AmbiguousParallelSchedule"


def test_verified_prefix_is_kept_before_ambiguous_parallel_suffix(tmp_path):
    actions = [ScheduledAction("b", 2, "emit", {"event": "b"}, after=("a",)),
               ScheduledAction("c", 2, "emit", {"event": "c"}, after=("a",)),
               ScheduledAction("a", 2, "emit", {"event": "a"})]
    path, clock = scheduled_pack(tmp_path, actions)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), BlockedEvent)
        assert rt.state.events == ["a"] and rt.state.variables[clock] == 2


def test_missing_resume_binding_never_becomes_automatic_continue(tmp_path):
    path, _ = scheduled_pack(tmp_path, [ScheduledAction("pause", 1, "wait")])
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), BlockedEvent)
        rt.signal("guessed-event"); assert isinstance(rt.next(), BlockedEvent)
        assert pack.node(rt.state.node).data["operation"] == "UnverifiedEventBinding"


def test_unverified_end_does_not_return(tmp_path):
    path, _ = scheduled_pack(tmp_path, [ScheduledAction("a", 1, "dialogue", text="line")], end_verified=False)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); assert isinstance(rt.next(), DialogueEvent)
        assert isinstance(rt.next(), BlockedEvent) and len(rt.state.frames) == 1


def test_exact_normalization_retains_gender_and_resource_type():
    assert normalize_resource(r"ASSETS\ASBRES\Story\x.playable") == "story/x.playable"
    assert normalize_resource("Story/x_f.playable") != normalize_resource("Story/x.playable")
    assert normalize_resource("Story/x.prefab") != normalize_resource("Story/x.playable")
    with pytest.raises(ValueError): normalize_resource("Story/../secret")


@pytest.fixture(scope="module")
def actual_schedule(tmp_path_factory):
    root = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE")
    source = os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not root or not source: pytest.skip("Native Timeline samples required")
    directory = Path(root) / "m58-lossless-final/output/lossless"
    if not directory.is_dir(): pytest.skip("M5.8 lossless exports missing")
    report, bundle = build(directory, Path(source), Path(root) / "reference/DS104060102.json")
    path = tmp_path_factory.mktemp("actual-native-schedule") / "scheduled.storypack"
    validation = compile_story(bundle, path)
    return report, bundle, path, validation


def test_real_extended_track_layouts_and_marker_evidence(actual_schedule):
    report, _, _, _ = actual_schedule
    assert report["timelines"] == 15 and not report["structural_parse_errors"]
    assert sum("clips" in o for r in report["reports"] for o in r["objects"]) == 440
    assert sum(len(o.get("clips", [])) for r in report["reports"] for o in r["objects"]) == 187
    pauses = [o for r in report["reports"] for o in r["objects"] if o["class"] == "PauseMarkerClip"]
    assert len(pauses) == 26 and all(o["resume_condition"] is None for o in pauses)
    boundaries = [p for r in report["reports"] for p in r["pause_boundary_evidence"]]
    assert len(boundaries) == 26 and all(len(p["preceding_dialogue_candidates"]) == 1 for p in boundaries)
    assert sum(a.get("evidence", {}).get("matches_option_text", False) for r in report["reports"] for a in r["scheduled_actions"]) == 5
    assert all(not r["pure_visual_exemptions"] and not r["end_policy_verified"] for r in report["reports"])


def test_real_control_option_routes_are_literal_not_sentence_id_guesses(actual_schedule):
    report, _, _, _ = actual_schedule
    routes = report["control_relations"]["option_routes"]
    assert len(routes) == 9 and all(r["unique_listener"] for r in routes)
    option = next(r for r in routes if r["sentence_id"] == 146010204)
    assert option["literal_event"] == "TalkSentence_146010205"
    assert option["listeners"][0]["timeline_calls"] == ["Story/Discussion/Mission/1040601/DS10406010202.playable"]
    assert option["literal_event"] != "TalkSentence_" + str(option["sentence_id"])


def test_real_root_call_attempts_block_without_forged_dialogues(actual_schedule, tmp_path):
    report, b, path, validation = actual_schedule
    assert set(validation["missions"].values()) == {"BLOCKED"}
    with StoryPack(path) as pack:
        for m in b.missions:
            rt = Runtime(pack, m.id)
            event = rt.next()
            assert isinstance(event, BlockedEvent) and len(rt.state.frames) == 1
            assert pack.node(event.node).data["operation"] == "NativeTimelinePreflight"
        save = tmp_path / "blocked.save.json"; rt.save(save)
    with StoryPack(path) as pack:
        restored = Runtime.load(pack, save)
        assert isinstance(restored.next(), BlockedEvent) and len(restored.state.frames) == 1
    assert report["full_runtime_complete"] == 0


def test_real_scheduled_cli_is_independent(actual_schedule, tmp_path):
    _, bundle, path, _ = actual_schedule
    result = subprocess.run([sys.executable, "-m", "astralogue", "play", bundle.missions[0].id,
        "--pack", str(path), "--autosave", str(tmp_path / "autosave.json")], cwd=tmp_path,
        input="\n", text=True, encoding="utf-8", capture_output=True, timeout=20,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"})
    assert result.returncode == 0, result.stderr
    assert "NativeTimelinePreflight" in result.stdout and "本会话结束" not in result.stdout


def test_cutscene_alias_requires_explicit_path_and_matching_version(tmp_path):
    database = tmp_path / "index.sqlite"; index = NativeIndex(database)
    try:
        row = {"Name": "different", "Container": "assets/asbres/cutscene/x_f.playable", "Source": "b.block", "PathID": 1, "Type": "MonoBehaviour"}
        index.db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?)", ("sha",0,"1","MonoBehaviour",row["Container"],json.dumps(row))); index.db.commit()
    finally: index.close()
    baseline = tmp_path / "ir.json"
    write_json(baseline, {"metadata": {"source": {"revision": "same", "game_version": "4.6.0"},
        "hsr_metrics": {"m": {"timeline_references": [{"name": "CS_Test"}]}}}})
    config = tmp_path / "public/ExcelOutput/CutSceneConfig.json"
    write_json(config.parent.parent / "source.json", {"revision":"same","game_version":"4.6.0"})
    write_json(config, [{"CutSceneName":"CS_Test","CutScenePath":"CutScene/x.playable","IsPlayerInvolved":True}])
    result = target_report(database, baseline, config)
    assert result["exact_container_references"] == 0
    assert len(result["gender_suffix_candidates"]) == 1 and not result["gender_suffix_candidates"][0]["resolved"]
    write_json(config, [{"CutSceneName":"CS_Test","CutScenePath":"CutScene/x_f.playable"}])
    assert target_report(database, baseline, config)["exact_container_references"] == 1
    write_json(config.parent.parent / "source.json", {"revision":"other","game_version":"4.6.0"})
    with pytest.raises(ValueError, match="version"): target_report(database, baseline, config)


def test_real_mainline_timeline_has_verified_task_ownership(tmp_path):
    root = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE")
    source = os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not root or not source: pytest.skip("Mainline native resources required")
    directory = Path(root) / "m59-main-1000202/output/lossless"
    if not directory.is_dir(): pytest.skip("M5.9 mainline export missing")
    source = Path(source)
    definition = json.loads((source / "Config/Level/Mission/1000202/MissionInfo_1000202.partial.json").read_text(encoding="utf-8"))
    submission = next(r for r in definition["SubMissionList"] if r["ID"] == 100020111)
    assert submission["MainMissionID"] == 1000202
    control = source / "Story/Mission/1000201/Story100020111.json"
    report, bundle = build(directory, source, control)
    assert report["timelines"] == 1 and not report["structural_parse_errors"]
    assert report["reports"][0]["validation"]["objects_verified"] == 742
    assert len(report["reports"][0]["hierarchy"]) == 59
    assert len(report["reports"][0]["scheduled_actions"]) == 272
    path = tmp_path / "main-native.storypack"; compile_story(bundle, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, bundle.missions[0].id)
        assert isinstance(rt.next(), BlockedEvent) and len(rt.state.frames) == 1
    from astralogue.compiler.hsr_mainline import MainlineCompiler
    from astralogue.hsr.sources import ResourceError
    linked = MainlineCompiler(source, native_bundles=[bundle]).compile()
    reference = next(r for r in linked.metadata["hsr_metrics"]["hsr:mission:1000202"]["timeline_references"]
                     if r["name"] == "Story/Mission/1000201/Story10002011101.playable")
    assert reference["native_graph_linked"] and reference["native_schedule_status"] == "BLOCKED"
    entry = bundle.metadata["native_timeline_entries"][reference["name"]]["entry"]
    assert any(e.kind == "call" and e.target == entry for e in linked.edges)
    bundle.metadata["source"]["revision"] = "different-revision"
    with pytest.raises(ResourceError, match="版本"): MainlineCompiler(source, native_bundles=[bundle])


def test_scan_checkpoint_reuses_hash_and_rescans_changed_content(tmp_path, monkeypatch):
    game = tmp_path / "game"; game.mkdir(); (game / "StarRail.exe").touch()
    (game / "config.ini").write_text("[General]\ngame_version=4.6.0\n")
    (game / "pkg_version").write_text("fixed-package-version")
    folder = game / "StarRail_Data/StreamingAssets/Asb/Windows"; folder.mkdir(parents=True)
    block = folder / "one.block"; block.write_bytes(b"AAAA")
    executable = tmp_path / "tool.exe"; executable.touch()
    staging = tmp_path / "staging"; staging.mkdir()
    database = tmp_path / "index.sqlite"; calls = []
    def fake_run(self, inputs, name, **kwargs):
        calls.append(name); run = staging / name; (run / "output").mkdir(parents=True)
        mp = run / "output/assets_map.json"; write_json(mp, {"GameType": "SR", "AssetEntries": []})
        record = {"game_version": "4.6.0", "command": ["--map_op"], "returncode": 0, "asset_count": 0,
                  "inputs": [{"staged": str(p), "sha256": file_hash(p), "bytes": p.stat().st_size} for p in inputs],
                  "outputs": [{"path": "output/assets_map.json", "sha256": file_hash(mp)}]}
        write_json(run / "run.json", record); (run / "tool.log").write_text("[Info] Finished")
        return record
    monkeypatch.setattr("astralogue.hsr.native_scan.AnimeStudio.run", fake_run)
    assert scan(game, executable, staging, database, "4.6.0", max_batches=1)["full_map_complete"]
    assert scan(game, executable, staging, database, "4.6.0", max_batches=1)["full_map_complete"]
    assert len(calls) == 1
    original_stat = block.stat()
    block.write_bytes(b"BBBB")  # same name and size, same package version
    os.utime(block, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert scan(game, executable, staging, database, "4.6.0", max_batches=1)["full_map_complete"]
    assert len(calls) == 2
    index = NativeIndex(database)
    try: assert index.db.execute("SELECT count(*) FROM blocks").fetchone()[0] == 2
    finally: index.close()
