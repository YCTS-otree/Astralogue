"""Real native reading projections; resources absent => explicitly skipped."""
import itertools
import os
from pathlib import Path
import subprocess
import sys

import pytest

from astralogue.compiler import compile_story
from astralogue.hsr.reconstruction import reconstruct
from astralogue.model import load_json
from astralogue.narrative import audit
from astralogue.runtime import BlockedEvent, ChoiceEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack


@pytest.fixture(scope="module")
def actual_reader(tmp_path_factory):
    native, source = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE"), os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not native or not source: pytest.skip("M6 requires real native export and public source")
    native, source = Path(native), Path(source)
    control = native / "reference/DS104060102.json"
    directory = native / "m58-lossless-final/output/lossless"
    if not control.exists() or not directory.is_dir(): pytest.skip("Discussion1040601 lossless exports missing")
    report, bundle = reconstruct(directory, source, control)
    path = tmp_path_factory.mktemp("native-reader") / "reader.storypack"
    compile_story(bundle, path)
    return report, bundle, path


def run_path(pack, mid, decisions, save=None):
    rt = Runtime(pack, mid)
    decisions = iter(decisions)
    lines, transcript_input = [], []
    for _ in range(250):
        event = rt.next()
        if isinstance(event, DialogueEvent):
            lines.append(pack.node(event.node).data["talk_sentence_id"]); transcript_input.append("")
        elif isinstance(event, ChoiceEvent):
            node = pack.node(event.node)
            value = next(decisions) if not node.data.get("reader_action") else event.options[0].value
            # Real sample's selected text projection has only one Track per call;
            # never silently choose among several unknown activations/orderings.
            if node.data.get("reader_action"): assert len(event.options) == 1
            index = next(i for i, opt in enumerate(event.options) if opt.value == value)
            rt.choose(value); transcript_input.append(str(index + 1))
        else:
            assert isinstance(event, EndEvent), event
            if save: rt.save(save)
            return lines, rt, "\n".join(transcript_input + ["", ""])
    pytest.fail("Reading exceeded 250 events")


def test_all_27_real_discussion_routes_preserve_original_options(actual_reader, tmp_path):
    report, _, path = actual_reader
    assert report["native_resources"] == 15 and report["dialogue_carriers"] == 26
    first = {204: [205, 206], 207: [208, 209, 210, 211], 212: [213, 214]}
    second = {217: [218], 219: [220], 221: [222, 223]}
    third = {227: [228], 229: [230, 231], 232: [233, 234]}
    seen = set()
    with StoryPack(path) as pack:
        assert isinstance(Runtime(pack, report["strict_mission"]).next(), BlockedEvent)
        for a, b, c in itertools.product(first, second, third):
            save = tmp_path / "save.json"
            lines, rt, _ = run_path(pack, report["reader_mission"], [str(146010000 + x) for x in [a, b, c]], save)
            expected = [202, 203] + first[a] + [215, 216] + second[b] + [224, 225, 226] + third[c] + [235, 236]
            assert lines == [146010000 + x for x in expected]
            seen.update(lines)
            trace = audit(pack, load_json(save))
            original = [r for r in trace["records"] if r["action"] == "original_choice"]
            assert len(original) == 3 and all(r["evidence"]["origin"] == "original_control" for r in original)
            assert trace["reading_end_reached"] and not trace["original_game_completion_proven"]
            assert isinstance(Runtime.load(pack, save).next(), EndEvent)
            rt.back(); assert isinstance(rt.next(), ChoiceEvent)
        assert len(seen) == 26
        option = next(r for r in report["original_option_routes"] if r["sentence_id"] == 146010227)
        assert option["literal_event"] == "Wait_Option_104060102_82"


def test_real_reader_has_separate_evidence_and_policies(actual_reader):
    report, b, _ = actual_reader
    info = b.metadata["narrative"]
    assert len([k for k in info["source_hashes"] if k.startswith("serialized_file:")]) == 15
    native = [r for r in info["relations"].values() if r["origin"] == "native_structure"]
    assert native and all(not r["verified"] for r in native if r["policy"])
    assert not info.get("patches") and report["strict_complete_named_missions"] == 0
    assert "raw_control" in info and "native_evidence" in b.metadata


def test_real_choice_save_restore_and_original_text(actual_reader, tmp_path):
    report, _, path = actual_reader
    source = Path(os.environ["ASTRALOGUE_HSR_MAINLINE_SOURCE"])
    rows = {r["TalkSentenceID"]: r for r in load_json(source / "ExcelOutput/TalkSentenceConfig.json") if "TalkSentenceID" in r}
    textmap = load_json(source / "TextMap/TextMapCHS.json")
    with StoryPack(path) as pack:
        rt = Runtime(pack, report["reader_mission"])
        for _ in range(80):
            e = rt.next()
            if isinstance(e, DialogueEvent):
                sid = pack.node(e.node).data["talk_sentence_id"]
                assert e.text == textmap[str(rows[sid]["TalkSentenceText"]["Hash"])]
            elif isinstance(e, ChoiceEvent):
                if not pack.node(e.node).data.get("reader_action"): break
                rt.choose(e.options[0].value)
            else: pytest.fail(str(e))
        else: pytest.fail("Original choice never reached")
        save = tmp_path / "choice.save.json"; rt.save(save)
        restored = Runtime.load(pack, save)
        assert restored.next() == e
        restored.choose("146010204"); restored.back()
        assert restored.next() == e
        restored.choose("146010212")
        for _ in range(25):
            event = restored.next()
            if isinstance(event, ChoiceEvent): restored.choose(event.options[0].value)
            elif isinstance(event, DialogueEvent):
                assert pack.node(event.node).data["talk_sentence_id"] == 146010213
                break
            else: pytest.fail(str(event))
        else: pytest.fail("Chosen branch missing")


def test_real_reader_cli_in_empty_directory_and_audit(actual_reader, tmp_path):
    report, _, path = actual_reader
    with StoryPack(path) as pack:
        _, _, input_ = run_path(pack, report["reader_mission"], ["146010204", "146010217", "146010227"])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}
    for key in list(env):
        if key.startswith("ASTRALOGUE_HSR_"): env.pop(key)
    save = tmp_path / "save.json"
    result = subprocess.run([sys.executable, "-m", "astralogue", "reader", "play", "--pack", str(path), "--autosave", str(save)],
                            cwd=tmp_path, env=env, input=input_, text=True, encoding="utf8", capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Reader 所选文字阅读段结束" in result.stdout and "非原游戏完整执行" in result.stdout
    with StoryPack(path) as pack: assert audit(pack, load_json(save))["reading_end_reached"]


def test_real_mainline_submission_reading_is_not_full_mission(tmp_path):
    native, source = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE"), os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not native or not source: pytest.skip("Mainline native resources required")
    directory = Path(native) / "m59-main-1000202/output/lossless"
    if not directory.is_dir(): pytest.skip("Mainline lossless export missing")
    source = Path(source)
    report, b = reconstruct(directory, source, source / "Story/Mission/1000201/Story100020111.json")
    path = tmp_path / "main-reader.storypack"; compile_story(b, path)
    with StoryPack(path) as pack:
        lines, _, _ = run_path(pack, report["reader_mission"], [])
        assert lines == list(range(100020314, 100020328)) + [100020360, 100020361, 100020362]
        assert isinstance(Runtime(pack, report["strict_mission"]).next(), BlockedEvent)
    assert report["strict_complete_named_missions"] == report["reader_complete_named_missions"] == 0
