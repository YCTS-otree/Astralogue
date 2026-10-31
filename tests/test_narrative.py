"""Reader policy isolation and source-bound community overlay regression tests."""
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from astralogue.cli import app
from astralogue.compiler import compile_story
from astralogue.model import Bundle, Mission, Node, digest, load_json
from astralogue.narrative import Reconstruction, audit
from astralogue.narrative.patch import apply_patch, validate_patch
from astralogue.runtime import BlockedEvent, ChoiceEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack


@pytest.fixture
def projection():
    strict = Bundle(metadata={"version": "1.5.0"})
    strict.text("default-title", "结构测试"); strict.text("title", "Strict")
    strict.missions = [Mission("strict", "title", "boundary")]
    strict.nodes = [Node("boundary", "strict", "unknown", data={"operation": "UnknownPause"})]
    r = Reconstruction(strict, "reader", "Reader", "consent")
    r.confirm("consent", "gap", "用户确认文字投影")
    r.node("gap", "unknown", operation="UncertainNext")
    r.node("end", "end")
    r.info.update(game="structural-test", game_version="v-test", source_hashes={"control": "a" * 64})
    r.info["modes"]["strict"] = {"mode": "strict"}
    return r


def document(r, status="pending"):
    return {"patch_version": 1, "id": "test-link", "status": status, "game": "structural-test", "game_version": "v-test",
            "source_hashes": deepcopy(r.info["source_hashes"]), "evidence": [{"id": "e1", "uri": "test:structural-proof"}],
            "operations": [{"op": "connect", "mission": "reader", "source": "gap", "target": "end", "evidence": ["e1"]}],
            "review": {"reviewer": "local test reviewer", "reviewed_at": "2026-10-31", "evidence": ["e1"]}}


def package(tmp_path, b):
    path = tmp_path / "test.storypack"
    compile_story(b, path, force=True)
    return StoryPack(path)


def test_reader_confirmation_does_not_change_strict(projection, tmp_path):
    before = deepcopy(projection.bundle.nodes[0])
    projection.guide("guide", {"end": "未知后续"})
    projection.confirm("gap-consent", "guide", "未知暂停")
    # Unknown control still blocks, even in a pack that includes Reader nodes.
    with package(tmp_path, projection.bundle) as p:
        assert isinstance(Runtime(p, "strict").next(), BlockedEvent)
        rt = Runtime(p, "reader")
        assert isinstance(rt.next(), ChoiceEvent)
        rt.choose("confirm")
        assert isinstance(rt.next(), BlockedEvent)
    assert projection.bundle.nodes[0] == before


def test_manual_guide_audit_back_and_restore(projection, tmp_path):
    node = next(n for n in projection.bundle.nodes if n.id == "gap")
    projection.bundle.nodes.remove(node)
    projection.guide("gap", {"end": "人工指定后续"})
    with package(tmp_path, projection.bundle) as p:
        rt = Runtime(p, "reader"); rt.choose("confirm")
        assert rt.next().options[0].text.startswith("非官方引导")
        rt.choose("end"); assert isinstance(rt.next(), EndEvent)
        save = tmp_path / "read.save.json"; rt.save(save)
        records = audit(p, load_json(save))
        assert records["reading_end_reached"] and not records["original_game_completion_proven"]
        assert [r["action"] for r in records["records"]] == ["confirmation", "manual_guide"]
        rt = Runtime.load(p, save); rt.back()
        assert rt.state.node == "gap" and len(rt.state.choices) == 1


def test_same_time_requires_user_order_and_remembers_visited(projection, tmp_path):
    b = projection.bundle
    b.nodes = [n for n in b.nodes if n.id != "gap"]
    for label in ["a", "b"]:
        b.text(label, "结构 " + label)
        b.nodes.append(Node(label, "reader", "dialogue", label))
        projection.node(label + ":exit", "noop")
        projection.edge(label, label + ":exit", "native_structure")
    projection.unordered("gap", [("a", "a:exit", "a"), ("b", "b:exit", "b")], "end")
    with package(tmp_path, b) as p:
        rt = Runtime(p, "reader"); rt.choose("confirm")
        assert len(rt.next().options) == 2
        rt.choose("1"); assert rt.next().text == "结构 b"
        assert len(rt.next().options) == 1
        rt.choose("0"); assert rt.next().text == "结构 a"
        assert isinstance(rt.next(), EndEvent)


def test_pending_patch_requires_explicit_opt_in(projection):
    p = document(projection)
    assert validate_patch(projection.bundle, p)["valid"]
    with pytest.raises(ValueError, match="待审核"): apply_patch(projection.bundle, p)
    changed = apply_patch(projection.bundle, p, True)
    assert changed.metadata["narrative"]["patches"][p["id"]]["document"] == p
    assert next(n for n in projection.bundle.nodes if n.id == "gap").kind == "unknown"


def test_inferred_relation_cannot_silently_become_verified(projection):
    with pytest.raises(ValueError, match="文字体验策略"):
        projection.edge("gap", "end", "inferred")
    edge = projection.edge("gap", "end", "inferred", policy="manual_guide")
    assert not projection.info["relations"][edge]["verified"]


def test_patch_false_condition_blocks_instead_of_forcing_progress(projection, tmp_path):
    p = document(projection, "reviewed")
    p["operations"][0].update(op="condition", condition=False)
    with package(tmp_path, apply_patch(projection.bundle, p)) as sp:
        rt = Runtime(sp, "reader"); rt.choose("confirm")
        assert isinstance(rt.next(), BlockedEvent)


def test_patch_conflicting_operations_and_invalid_document_are_rejected(projection):
    p = document(projection)
    p["operations"] *= 2
    assert not validate_patch(projection.bundle, p)["valid"]
    assert not validate_patch(projection.bundle, [])["valid"]


@pytest.mark.parametrize("case", ["hash", "game", "version", "missing", "ownership", "cycle", "condition", "variable", "evidence", "review", "op"])
def test_patch_rejects_invalid_revisions(projection, case):
    p = document(projection, "reviewed"); op = p["operations"][0]
    if case == "hash": p["source_hashes"]["control"] = "b" * 64
    elif case == "game": p["game"] = "other"
    elif case == "version": p["game_version"] = "other"
    elif case == "missing": op["target"] = "missing"
    elif case == "ownership": op["target"] = "boundary"
    elif case == "cycle": op["target"] = "consent"
    elif case == "condition": op.update(op="condition", condition={"python": "unsafe"})
    elif case == "variable": op.update(op="condition", condition={"eq": [{"var": "missing"}, True]})
    elif case == "evidence": op["evidence"] = ["missing"]
    elif case == "review": p.pop("review")
    elif case == "op": op["op"] = "guess"
    assert not validate_patch(projection.bundle, p)["valid"]


def test_patch_never_overrides_verified_original_edges(projection):
    projection.edge("gap", "end", "original_control", {"test": "explicit relation"})
    p = document(projection, "reviewed")
    p["operations"][0]["replace_edge"] = projection.bundle.edges[-1].id
    assert "已验证" in validate_patch(projection.bundle, p)["errors"][0]
    p["operations"][0].update(source="boundary", target="boundary", mission="strict")
    assert "Strict" in validate_patch(projection.bundle, p)["errors"][0]


def test_replaced_policy_is_archived_without_dangling_active_relation(projection):
    p = document(projection, "reviewed")
    old = next(e for e in projection.bundle.edges if e.source == "consent")
    p["operations"][0].update(source="consent", target="end", replace_edge=old.id, op="order")
    b = apply_patch(projection.bundle, p)
    info = b.metadata["narrative"]
    assert old.id not in info["relations"] and all(e.id != old.id for e in b.edges)
    archive = info["patches"][p["id"]]
    assert archive["original_reader_edges"][0]["edge"]["target"] == "gap"
    assert archive["original_reader_policies"]["consent"]["official"] is False
    assert next(n for n in b.nodes if n.id == "boundary").kind == "unknown"


def test_patch_event_and_condition_are_auditable(projection, tmp_path):
    p = document(projection, "reviewed")
    p["operations"][0].update(op="event", event="supplemental", condition=True)
    b = apply_patch(projection.bundle, p)
    assert digest(b.to_dict()) == digest(apply_patch(projection.bundle, p).to_dict())
    with package(tmp_path, b) as sp:
        rt = Runtime(sp, "reader"); rt.choose("confirm")
        assert "非官方补丁" in rt.next().options[0].text
        rt.choose("confirm"); assert isinstance(rt.next(), EndEvent)
        assert "supplemental" in rt.state.events
        save = tmp_path / "save.json"; rt.save(save)
        trace = audit(sp, load_json(save))
        assert trace["records"][-1]["evidence"]["origin"] == "community_reviewed"
        assert not trace["records"][-1]["evidence"]["verified"]
    with pytest.raises(ValueError, match="已应用"): apply_patch(b, p)


def test_patch_cli_create_import_validate_apply_and_rebuild(projection, tmp_path):
    source, patch, imported = [tmp_path / n for n in ["base.json", "patch.json", "imported.json"]]
    projection.bundle.write(source)
    runner = CliRunner()
    args = ["--source", str(source)]
    result = runner.invoke(app, ["patch", "create", *args, "--output", str(patch), "--patch-id", "test",
                                "--mission", "reader", "--from-node", "gap", "--to-node", "end", "--evidence-uri", "test:proof"])
    assert result.exit_code == 0, result.output
    for command in [["validate"], ["import", "--output", str(imported)]]:
        result = runner.invoke(app, ["patch", *command, *args, "--patch", str(patch)])
        assert result.exit_code == 0, result.output
    output, ir = tmp_path / "patched.storypack", tmp_path / "patched.json"
    cmd = ["patch", "apply", *args, "--patch", str(imported), "--output", str(output), "--output-ir", str(ir), "--include-pending"]
    result = runner.invoke(app, cmd); assert result.exit_code == 0, result.output
    assert load_json(source) == projection.bundle.to_dict()
    with StoryPack(output) as sp: first = sp.metadata["pack_id"]
    result = runner.invoke(app, cmd + ["--force"]); assert result.exit_code == 0, result.output
    with StoryPack(output) as sp: assert first == sp.metadata["pack_id"]
    for ir_target, pack_target in [(ir, source), (imported, output), (ir, ir)]:
        result = runner.invoke(app, ["patch", "apply", *args, "--patch", str(imported), "--output-ir", str(ir_target),
                                   "--output", str(pack_target), "--include-pending", "--force"])
        assert result.exit_code != 0 and "不能覆盖" in result.output
    assert load_json(source) == projection.bundle.to_dict()
