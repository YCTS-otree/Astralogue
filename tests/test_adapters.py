from copy import deepcopy
import json
import sqlite3
import pytest

from astralogue.adapters import discover, import_source
from astralogue.compiler import compile_story
from astralogue.model import load_json
from astralogue.runtime import BlockedEvent, ChoiceEvent, DiagnosticEvent, Runtime
from astralogue.storypack import StoryPack
from astralogue.validation import validate


def task(kind, **fields): return {"$type": "RPG.GameCore." + kind, **fields}
def seq(*tasks): return {"TaskList": list(tasks)}
def wait(event): return task("WaitCustomString", CustomString={"Value": event})
def emit(event): return task("TriggerCustomString", CustomString={"Value": event})


@pytest.fixture
def raw(tmp_path):
    root = tmp_path / "raw"
    def write(path, obj):
        p = root / path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")
    write("ExcelOutput/TalkSentenceConfig.json", [
        {"TalkSentenceID": 1, "TalkSentenceText": {"Hash": 101}},
        {"TalkSentenceID": 2, "TalkSentenceText": {"Hash": 102}},
        {"TalkSentenceID": 3, "TalkSentenceText": {"Hash": 103}}])
    write("TextMap/TextMapCHS.json", {"101": "选项标识", "102": "分支标识", "103": "汇合标识"})
    obj = {"OnInitSequece": [], "OnStartSequece": [
        seq(task("PlayOptionTalk", OptionList=[{"TalkSentenceID": 1, "TriggerCustomString": "branch"}])),
        seq(wait("branch"), task("PlayAndWaitSimpleTalk", SimpleTalkList=[{"TalkSentenceID": 2}]), emit("merge")),
        seq(wait("merge"), task("PlayAndWaitSimpleTalk", SimpleTalkList=[{"TalkSentenceID": 3}]), task("EndPerformance")),
        seq(task("WaitPerformanceEnd"), task("FinishLevelGraph"))]}
    write("Config/Level/Mission/Test/Act/a.json", obj)
    return root, obj, write


def test_auto_discovery_and_raw_branch(raw, tmp_path):
    root, _, _ = raw
    assert discover(root) == "hsr"
    b = import_source(root, ["CHS"])
    assert validate(b)["missions"][b.missions[0].id] == "RESOLVED"
    assert len(b.metadata["inputs"]) == 3
    assert b.source_refs
    out = tmp_path / "raw.storypack"; compile_story(b, out)
    with StoryPack(out) as pack:
        rt = Runtime(pack, b.missions[0].id)
        assert isinstance(rt.next(), ChoiceEvent)
        rt.choose("1"); event = rt.next()
        assert pack.node(event.node).data["sentence_id"] == 2
        assert pack.node(rt.next().node).data["sentence_id"] == 3


def test_same_raw_trigger_preserves_distinct_choices(raw):
    root, obj, write = raw
    obj["OnStartSequece"][0]["TaskList"][0]["OptionList"].append({"TalkSentenceID": 1, "TriggerCustomString": "branch"})
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    edges = [e for e in b.edges if e.kind == "option"]
    assert len(edges) == 2 and edges[0].target == edges[1].target


def test_concurrent_root_never_concatenated(raw):
    root, obj, write = raw
    obj["OnStartSequece"].append(seq(task("EndPerformance")))
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert b.missions[0].entry is None
    assert validate(b)["missions"][b.missions[0].id] == "BLOCKED"


def test_multiple_waiters_are_not_guessed(raw):
    root, obj, write = raw
    obj["OnStartSequece"].append(seq(wait("branch"), task("EndPerformance")))
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert any(d.code == "event_target" for d in b.diagnostics)
    assert any(n.kind == "unknown" for n in b.nodes)


@pytest.mark.parametrize("mutation", [
    lambda obj: obj["OnStartSequece"][0]["TaskList"][0]["OptionList"][0].update({"Predicate": {"unknown": True}}),
    lambda obj: obj["OnStartSequece"][0]["TaskList"][0].update({"SuccessTaskList": [emit("merge")]}),
])
def test_unknown_option_control_fields_block(raw, mutation):
    root, obj, write = raw; mutation(obj)
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert next(n for n in b.nodes if n.id == b.missions[0].entry).kind == "unknown"


def test_nonterminal_trigger_not_linearized(raw):
    root, obj, write = raw
    obj["OnStartSequece"][1]["TaskList"].append(task("EndPerformance"))
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert any(n.kind == "unknown" and n.data.get("operation") == "TriggerCustomString" for n in b.nodes)


def test_wait_name_does_not_invent_dialogue(raw):
    root, obj, write = raw
    obj["OnStartSequece"][0]["TaskList"][0]["OptionList"][0]["TriggerCustomString"] = "TalkSentence_2"
    obj["OnStartSequece"][1]["TaskList"][0] = wait("TalkSentence_2")
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert [n.data.get("sentence_id") for n in b.nodes if n.kind == "dialogue"] == [2, 3]


def test_missing_language_is_clear(raw):
    root, _, _ = raw
    with pytest.raises(ValueError, match="TextMap"): import_source(root, ["EN"])


def test_dictionary_config_supported(raw):
    root, _, write = raw
    rows = load_json(root / "ExcelOutput/TalkSentenceConfig.json")
    write("ExcelOutput/TalkSentenceConfig.json", {str(r["TalkSentenceID"]): r for r in rows})
    assert import_source(root, ["CHS"]).missions


def test_jsonl_keeps_only_explicit_links(tmp_path):
    path = tmp_path / "story.jsonl"
    path.write_text(json.dumps([
        {"type": "RPG.GameCore.PlayOptionTalk", "options": [{"TalkSentenceID": 10, "content": "option", "next_TalkSentenceID": "11"}]},
        {"type": "RPG.GameCore.PlayAndWaitSimpleTalk", "conversations": [{"TalkSentenceID": 11, "content": "line"}], "next_TalkSentenceID": 12},
        {"type": "RPG.GameCore.PlayAndWaitSimpleTalk", "conversations": [{"TalkSentenceID": 12, "content": "line2"}]},
        {"type": "RPG.GameCore.EndPerformance"}]) + "\n", encoding="utf-8")
    b = import_source(path, ["CHS"])
    assert len(b.edges) == 2
    assert any(e.kind == "option" for e in b.edges)
    assert validate(b)["missions"][b.missions[0].id] == "BLOCKED"
    assert b.source_refs[0]["raw"]


def test_sqlite_loss_is_explicit(tmp_path):
    p = tmp_path / "third.db"
    con = sqlite3.connect(p)
    try:
        con.executescript("""
        CREATE TABLE dialogue_group(group_id,mission_id,act_file,sequence_index,wait_custom_string);
        CREATE TABLE dialogue_line(group_id,sort_order,talk_type,talk_sentence_id,text_hash,name_hash,option_group_index,trigger_custom_string);
        CREATE TABLE text_map(hash,lang,text);
        CREATE TABLE group_triggers(group_id,trigger);
        INSERT INTO dialogue_group VALUES(1,'mission','act',0,NULL);
        INSERT INTO dialogue_line VALUES(1,0,'simple_talk',7,'123',NULL,NULL,NULL);
        INSERT INTO text_map VALUES('123','CHS','imported');
        INSERT INTO group_triggers VALUES(1,'merge');
        """); con.commit()
    finally: con.close()
    b = import_source(p, ["CHS"])
    assert b.texts["export:text:123"]["CHS"] == "imported"
    assert b.metadata["group_triggers"][0]["trigger"] == "merge"
    assert any(n.kind == "dialogue" for n in b.nodes)
    assert validate(b)["missions"][b.missions[0].id] == "BLOCKED"
    p.rename(tmp_path / "closed.db")


def test_unsupported_sqlite_schema(tmp_path):
    p = tmp_path / "other.db"; con = sqlite3.connect(p); con.close()
    with pytest.raises(ValueError, match="Schema"): import_source(p, ["CHS"])


def test_presentation_cannot_hide_nested_control(raw):
    root, obj, write = raw
    obj["OnStartSequece"].append(seq(task("LevelPerformanceInitialize", SuccessTaskList=[emit("branch")])))
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert b.missions[0].entry is None
    assert any(n.kind == "unknown" and n.data.get("operation") == "LevelPerformanceInitialize" for n in b.nodes)


def test_source_manifest_mismatch_is_reported(raw):
    root, _, write = raw
    write("source.json", {"revision": "claimed", "files": {"ExcelOutput/TalkSentenceConfig.json": "incorrect"}})
    b = import_source(root, ["CHS"])
    assert any(d.code == "source_hash_mismatch" for d in b.diagnostics)
    assert validate(b)["missions"][b.missions[0].id] == "BLOCKED"


def test_explicit_simple_talk_await_pair(raw, tmp_path):
    root, obj, write = raw
    tasks = obj["OnStartSequece"][1]["TaskList"]
    tasks[1] = task("PlaySimpleTalk", SimpleTalkList=[{"TalkSentenceID": 2, "TextSpeed": 0, "ProtectTime": 0}])
    tasks.insert(2, task("WaitSimpleTalkFinish"))
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert validate(b)["missions"][b.missions[0].id] == "RESOLVED"
    out = tmp_path / "async.storypack"; compile_story(b, out)
    with StoryPack(out) as pack:
        rt = Runtime(pack, b.missions[0].id); rt.next(); rt.choose("1")
        assert pack.node(rt.next().node).data["sentence_id"] == 2


def test_unawaited_simple_talk_blocks(raw):
    root, obj, write = raw
    obj["OnStartSequece"][1]["TaskList"][1] = task("PlaySimpleTalk", SimpleTalkList=[{"TalkSentenceID": 2}])
    write("Config/Level/Mission/Test/Act/a.json", obj)
    b = import_source(root, ["CHS"])
    assert any(n.kind == "unknown" and n.data.get("operation") == "PlaySimpleTalk" for n in b.nodes)
