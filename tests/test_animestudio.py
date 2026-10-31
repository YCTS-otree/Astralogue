import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astralogue.hsr.animestudio import AnimeStudio, inspect_native, load_map, timeline_matches


def entry(**kw):
    return {"Name": "CS_Test", "Container": "assets/story/CS_Test.playable", "Source": "x.block",
            "PathID": 2**60 + 1, "Type": "MonoBehaviour", "Offset": 12, "Hash": "abc", **kw}


def test_map_preserves_integer_and_unknown_metadata(tmp_path):
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"GameType": "SR", "AssetEntries": [entry(extra={"future": 1})]}))
    assert load_map(p)[0] == entry(extra={"future": 1})
    p.write_text('{"GameType":"GI", "AssetEntries":[]}')
    with pytest.raises(ValueError): load_map(p)


def test_matching_is_exact_and_retains_conflicts():
    matches = timeline_matches([entry(), entry(PathID=3), entry(Name="CS_TestExtra", Container="other")], ["CS_Test", "CS_Missing"])
    assert len(matches["CS_Test"]) == 2
    assert matches["CS_Missing"] == []


def test_native_null_is_not_deserialized(tmp_path):
    p = tmp_path / "asset.json"; p.write_text("null")
    assert not inspect_native(p)["structured"]
    p.write_bytes(b"\x00\xff")
    assert not inspect_native(p)["ir_converted"]


def test_native_references_retained_without_inventing_execution(tmp_path):
    p = tmp_path / "asset.json"
    raw = {"m_Tracks": [{"m_FileID": 1, "m_PathID": 9007199254740993}], "m_Clips": [{"start": 0}]}
    p.write_text(json.dumps(raw))
    r = inspect_native(p)
    assert r["raw"] == raw and r["structured"]
    assert r["references"][0]["raw"]["m_PathID"] == 9007199254740993
    assert not r["ir_converted"] and not r["runtime_verified"]


def setup_tool(tmp_path):
    game = tmp_path / "game"; game.mkdir(); (game / "StarRail.exe").touch()
    (game / "config.ini").write_text("[General]\ngame_version=4.6.0\n")
    exe = tmp_path / "cli.exe"; exe.write_bytes(b"test")
    block = game / "x.block"; block.write_bytes(b"ENCR sample")
    return game, exe, block


def test_subprocess_only_sees_copies(tmp_path, monkeypatch):
    game, exe, block = setup_tool(tmp_path)
    def run(args, **kwargs):
        copied = Path(args[1])
        assert not copied.is_relative_to(game)
        assert (copied / block.name).read_bytes() == block.read_bytes()
        (copied / block.name).write_bytes(b"tool mutation")
        assert kwargs["cwd"].is_relative_to(tmp_path / "staging")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("astralogue.hsr.animestudio.subprocess.run", run)
    result = AnimeStudio(exe, game, tmp_path / "staging", "4.6.0").run([block], "test")
    assert block.read_bytes() == b"ENCR sample"
    assert result["outputs"] == []  # exit zero alone is no extraction evidence
    assert result["inputs"][0]["sha256"]


def test_paths_and_duplicate_inputs_rejected(tmp_path):
    game, exe, block = setup_tool(tmp_path)
    with pytest.raises(ValueError): AnimeStudio(exe, game, game / "out", "4.6.0")
    tool = AnimeStudio(exe, game, tmp_path / "staging", "4.6.0")
    with pytest.raises(ValueError): tool.run([block], "../escape")
    with pytest.raises(ValueError): tool.run([block, block], "duplicates")
    outside = tmp_path / "x.block"; outside.touch()
    with pytest.raises(ValueError): tool.run([outside], "outside")


def test_version_mismatch_blocks(tmp_path):
    game, exe, block = setup_tool(tmp_path)
    with pytest.raises(ValueError, match="version"):
        AnimeStudio(exe, game, tmp_path / "staging", "4.5.0")


def test_mono_header_preserves_payload(tmp_path):
    import struct
    from astralogue.hsr.native_timeline import mono_header
    p = tmp_path / "clip.dat"
    p.write_bytes(struct.pack("<iqiiqi", 0, 0, 1, 0, 12345, 4) + b"Clip" + b"\x00\xff\x01\x02")
    h = mono_header(p)
    assert h["m_Name"] == "Clip" and h["payload_offset"] == 36
    assert h["payload_hex"] == "00ff0102" and h["control_semantics"] == "UNKNOWN"
    p.write_bytes(b"short")
    with pytest.raises(ValueError): mono_header(p)


def test_native_base_fields_are_partial(tmp_path):
    p = tmp_path / "clip.json"
    p.write_text(json.dumps({"m_Name": "Clip", "m_Script": {"m_PathID": 1, "m_FileID": 0}}))
    result = inspect_native(p)
    assert result["base_fields_only"] and not result["ir_converted"]


def test_native_graph_does_not_cross_files_or_schedule_tracks():
    from astralogue.hsr.native_timeline import reference_graph
    objects = [
        {"file": "a", "path_id": 1, "raw": {"m_Tracks": [{"m_FileID": 0, "m_PathID": 2}, {"m_FileID": 1, "m_PathID": 2}]}},
        {"file": "a", "path_id": 2, "raw": {}},
        {"file": "b", "path_id": 2, "raw": {}},
    ]
    result = reference_graph(objects)
    assert len(result["links"]) == len(result["unresolved"]) == 1
    assert not result["execution_edges"] and not result["ir_converted"]


def test_native_report_rejects_version_conflicts(tmp_path):
    from astralogue.hsr.animestudio import native_coverage
    baseline = tmp_path / "ir.json"
    baseline.write_text(json.dumps({"metadata": {"source": {"game_version": "4.6.0"},
        "hsr_metrics": {"mission": {"timeline_references": [{"name": "CS_Test"}]}}}}))
    run = tmp_path / "staging/run"; run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"game_version": "4.5.0", "outputs": []}))
    result = native_coverage(tmp_path / "staging", baseline)
    assert result["baseline_reference_occurrences"] == 1
    assert result["rejected_runs"] and result["located_reference_occurrences"] == 0


def test_real_native_exports(tmp_path):
    import os
    from astralogue.hsr.native_timeline import mono_header
    source = os.environ.get("ASTRALOGUE_HSR_NATIVE_SOURCE")
    if not source: pytest.skip("Set ASTRALOGUE_HSR_NATIVE_SOURCE for actual local-game exports")
    source = Path(source)
    raw = next((source / "discussion-raw/output").rglob("PlaySimpleTalkClip.dat"))
    converted = next((source / "discussion-convert/output").rglob("PlaySimpleTalkClip.json"))
    header = mono_header(raw)
    obj = inspect_native(converted)
    assert header["m_Name"] == obj["raw"]["m_Name"] == "PlaySimpleTalkClip"
    assert header["m_Script"] == obj["raw"]["m_Script"]
    assert header["payload_bytes"] > 0 and obj["base_fields_only"]
    # The real export is deliberately kept blocked, rather than falsely accepted.
    assert not obj["ir_converted"]
