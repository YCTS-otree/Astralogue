import sqlite3
import pytest

from astralogue.compiler import compile_story
from astralogue.model import Bundle, Diagnostic, load_json
from astralogue.runtime import Runtime
from astralogue.storypack import StoryPack
from astralogue.validation import validate


def test_close_reopen_readonly(pack_path):
    for _ in range(2):
        with StoryPack(pack_path) as pack:
            assert Runtime(pack, "m").next().node == "a"
            with pytest.raises(sqlite3.OperationalError): pack.con.execute("DELETE FROM texts")
    renamed = pack_path.with_name("moved.storypack")
    pack_path.rename(renamed)
    with StoryPack(renamed) as pack: assert pack.mission("m")["status"] == "RESOLVED"


def test_language_lookup_and_no_silent_fallback(pack_path):
    with StoryPack(pack_path) as pack:
        assert Runtime(pack, "m", "CHS").next().text.startswith("测试")
        assert Runtime(pack, "m", "EN").next().text == "Test a"
        with pytest.raises(ValueError): pack.text("a", "JP")
        with pytest.raises(ValueError): pack.text("missing", "CHS")


def test_byte_reproducibility(tmp_path, graph):
    a, b = tmp_path / "a.storypack", tmp_path / "b.storypack"
    r1 = compile_story(graph, a)
    graph.nodes.reverse(); graph.edges.reverse(); graph.missions.reverse()
    r2 = compile_story(graph, b)
    assert r1["pack_id"] == r2["pack_id"]
    assert a.read_bytes() == b.read_bytes()


def test_reject_overwrite(pack_path, graph):
    original = pack_path.read_bytes()
    with pytest.raises(ValueError): compile_story(graph, pack_path)
    assert pack_path.read_bytes() == original
    compile_story(graph, pack_path, force=True)


def test_version_gate(pack_path):
    with sqlite3.connect(pack_path) as con: con.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="迁移"): StoryPack(pack_path)


def test_ir_roundtrip(tmp_path, graph):
    path = tmp_path / "ir.json"; graph.write(path)
    assert Bundle.from_dict(load_json(path)).to_dict() == graph.to_dict()


def test_unknown_raw_preserved(tmp_path, graph):
    raw = {"$type": "UnknownOperation", "FutureField": {"value": 17}}
    graph.nodes[0].kind = "unknown"
    graph.source_refs.append({"node": "a", "file": "raw.json", "pointer": "/tasks/0", "original_id": 123, "raw": raw})
    path = tmp_path / "u.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        b = pack.bundle()
        assert b.source_refs[0]["raw"] == raw
        assert validate(b)["missions"]["m"] == "BLOCKED"


def test_schema_validation_stable(pack_path):
    with StoryPack(pack_path) as pack:
        assert validate(pack.bundle()) == validate(pack.bundle())


def test_duplicate_json_keys_rejected(tmp_path):
    p = tmp_path / "bad.json"; p.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复"): load_json(p)


def test_source_diagnostics_survive_code_collision(tmp_path, graph):
    graph.diagnostics.append(Diagnostic("missing_text", "upstream-specific", "warning", "m"))
    dest = tmp_path / "diag.storypack"; compile_story(graph, dest)
    with StoryPack(dest) as pack:
        assert any(d.message == "upstream-specific" for d in pack.bundle().diagnostics)


def test_save_cannot_overwrite_storypack(pack_path):
    content = pack_path.read_bytes()
    with StoryPack(pack_path) as pack:
        with pytest.raises(ValueError, match="覆盖"): Runtime(pack, "m").save(pack_path)
    assert pack_path.read_bytes() == content
