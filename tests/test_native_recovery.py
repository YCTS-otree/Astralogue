import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys

import pytest

from astralogue.http import verified_context
from astralogue.hsr.animestudio import write_json
from astralogue.hsr.lossless import validate_export
from astralogue.hsr.native_index import NativeIndex
from astralogue.hsr.native_story import recover_many
from astralogue.hsr.timeline_binary import Reader, clip, decode
from astralogue.compiler import compile_story
from astralogue.runtime import Runtime, DialogueEvent, BlockedEvent
from astralogue.storypack import StoryPack


def test_https_always_verifies_certificates_and_hostname():
    context = verified_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_truncated_native_fields_fail_closed():
    with pytest.raises(ValueError): Reader(b"\x00").read("q")
    with pytest.raises(ValueError): Reader(b"\xff" * 4).count()
    with pytest.raises(ValueError): clip(Reader(b"\x02\x00\x00\x00"))
    with pytest.raises(ValueError): Reader(b"\xff" * 4).string()


@pytest.fixture(scope="module")
def native_inputs():
    root = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE")
    source = os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not root or not source: pytest.skip("Native exports and original HSR tables required")
    root, source = Path(root), Path(source)
    export = root / "m58-lossless-final/output/lossless"
    control = root / "reference/DS104060102.json"
    if not export.is_dir() or not control.is_file(): pytest.skip("M5.8 lossless sample not available")
    return export, source, control


@pytest.fixture(scope="module")
def native_reports(native_inputs):
    export, source, _ = native_inputs
    rows = json.loads((source / "ExcelOutput/TalkSentenceConfig.json").read_text(encoding="utf-8"))
    ids = {r["TalkSentenceID"] for r in rows if "TalkSentenceID" in r}
    reports = [(p, decode(p, ids)) for p in sorted(export.glob("*/manifest.json"))]
    assert len(reports) == 15
    return reports


def test_real_lossless_objects_and_duplicate_names(native_reports):
    assert sum(r["validation"]["objects_verified"] for _, r in native_reports) == 1010
    for manifest, _ in native_reports:
        m = json.loads(manifest.read_text(encoding="utf-8-sig"))
        assert len({o["path_id"] for o in m["objects"]}) == m["object_count"]
        assert not validate_export(manifest)["known_references_unresolved"]
        assert not validate_export(manifest)["bundle_references_unresolved"]
    manifest = next(p for p, r in native_reports if any(o["name"] == "DS10406010201" for o in r["objects"]))
    m = json.loads(manifest.read_text(encoding="utf-8-sig"))
    duplicates = [o for o in m["objects"] if o["type"] == "MonoBehaviour" and o["name"] == "PlaySimpleTalkClip"]
    assert len(duplicates) == 2
    assert duplicates[0]["raw"] != duplicates[1]["raw"]


def test_real_lossless_corruption_rejected(native_reports, tmp_path):
    manifest = native_reports[0][0]
    copied = tmp_path / "sample"
    shutil.copytree(manifest.parent, copied)
    m = json.loads((copied / "manifest.json").read_text(encoding="utf-8-sig"))
    path = copied / m["objects"][0]["raw"]
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="hash"): validate_export(copied / "manifest.json")
    m["objects"].pop()
    write_json(copied / "manifest.json", m)
    with pytest.raises(ValueError, match="count"): validate_export(copied / "manifest.json")


def test_real_native_fields_and_unsorted_clip_timing(native_reports):
    talks = [o for _, r in native_reports for o in r["objects"] if "talk_sentence_id" in o]
    assert len(talks) == 26
    r = next(r for _, r in native_reports if any(o["name"] == "DS10406010201" for o in r["objects"]))
    objects = {o["path_id"]: o for o in r["objects"]}
    track = next(o for o in r["objects"] if o["class"] == "PlaySimpleTalkTrack")
    assert [c["start"] for c in track["clips"]] == [5, 15, 16, 26, 0]
    dialogue = [(c["start"], c["duration"], objects[c["asset"]["m_PathID"]].get("talk_sentence_id"))
                for c in track["clips"] if "talk_sentence_id" in objects[c["asset"]["m_PathID"]]]
    assert dialogue == [(5, 10, 146010202), (16, 10, 146010203)]
    assert all(o["unknown_payload_hex"] for o in talks)
    # Unsupported visual/game-specific layouts remain explicitly recorded.
    assert r["errors"] and r["unknown_control_semantics"]


def test_real_container_reference_tampering_rejected(native_reports, tmp_path):
    copied = tmp_path / "reference-check"
    shutil.copytree(native_reports[0][0].parent, copied)
    manifest = copied / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    bundle = next(o["asset_bundle"] for o in data["objects"] if o.get("asset_bundle"))
    bundle["containers"][0]["asset"]["m_PathID"] += 1
    write_json(manifest, data)
    with pytest.raises(ValueError, match="references differ"): validate_export(manifest)


@pytest.fixture(scope="module")
def native_pack(native_inputs, tmp_path_factory):
    export, source, control = native_inputs
    workspace = tmp_path_factory.mktemp("native-pack")
    inputs = workspace / "inputs"
    local_run = inputs / "run"
    local_export = local_run / "output/lossless"
    shutil.copytree(export, local_export)
    shutil.copyfile(export.parents[1] / "run.json", local_run / "run.json")
    local_source = inputs / "public"
    for relative in ("source.json", "ExcelOutput/TalkSentenceConfig.json", "TextMap/TextMapCHS.json"):
        target = local_source / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    local_control = inputs / "control.json"; shutil.copyfile(control, local_control)
    report, b = recover_many(local_export, local_source, local_control)
    assert report["verified_dialogue_clips"] == 26
    assert report["full_timelines_runtime_complete"] == 0
    for route in [x for r in report["reports"] for x in r["dialogue_routes"]]:
        assert len(route["track_path"]) >= 3
    target = workspace / "native.storypack"
    compile_story(b, target)
    assert inputs.resolve().is_relative_to(workspace.resolve()) and inputs.name == "inputs"
    shutil.rmtree(inputs)  # only this test's copies, never installation/source assets
    assert not inputs.exists()
    return target, b


def test_real_native_storypack_reopen_save_and_block(native_pack, tmp_path):
    path, b = native_pack
    save = tmp_path / "native.save.json"
    with StoryPack(path) as pack:
        rt = Runtime(pack, b.missions[0].id); rt.save(save)
    with StoryPack(path) as pack:
        rt = Runtime.load(pack, save)
        event = rt.next()
        assert isinstance(event, DialogueEvent)
        assert pack.node(event.node).data["talk_sentence_id"] in range(146010200, 146010300)
        assert isinstance(rt.next(), BlockedEvent)
        # Runtime backtracks choices, not arbitrary lines. This sample has none.
        with pytest.raises(ValueError, match="选择"): rt.back()
        assert isinstance(Runtime.load(pack, save).next(), DialogueEvent)
        assert pack.metadata["native_evidence"]


def test_real_native_cli_offline_without_sources(native_pack, tmp_path):
    path, b = native_pack
    copied = tmp_path / "standalone.storypack"; shutil.copyfile(path, copied)
    proc = subprocess.run([sys.executable, "-m", "astralogue", "play", b.missions[0].id,
                           "--pack", str(copied), "--autosave", str(tmp_path / "save.json")],
                          input="\n\n", capture_output=True, text=True, encoding="utf-8", timeout=20,
                          cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                             "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"})
    assert proc.returncode == 0, proc.stderr
    assert "NativeTimelineContinuation" in proc.stdout
    assert "本会话结束" not in proc.stdout


def test_incremental_native_index_idempotent_and_content_checked(tmp_path):
    import hashlib
    staging = tmp_path / "staging"; run = staging / "run"; out = run / "output"; out.mkdir(parents=True)
    block = tmp_path / "x.block"; block.write_bytes(b"ENCR sample")
    sha = hashlib.sha256(block.read_bytes()).hexdigest()
    mp = out / "assets_map.json"; write_json(mp, {"GameType": "SR", "AssetEntries": []})
    write_json(run / "run.json", {"outputs": [{"path": "output/assets_map.json", "sha256": hashlib.sha256(mp.read_bytes()).hexdigest()}],
        "command": ["--map_op"], "returncode": 0, "game_version": "4.6.0",
        "inputs": [{"staged": str(block), "sha256": sha, "bytes": block.stat().st_size}]})
    (run / "tool.log").write_text("[Info] Finished")
    index = NativeIndex(tmp_path / "index.sqlite")
    try:
        assert index.ingest(staging)["new_runs"] == 1
        assert index.ingest(staging)["new_runs"] == 0
        assert index.remaining([block]) == []
        block.write_bytes(b"changed file")
        assert index.remaining([block]) == [block]
    finally: index.close()
