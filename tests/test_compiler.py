from copy import deepcopy
import pytest

from astralogue.compiler import compile_story
from astralogue.model import Edge, Node
from astralogue.storypack import StoryPack
from astralogue.validation import validate
from astralogue.validation.explore import explore


@pytest.mark.parametrize("change,code", [
    (lambda b: setattr(b.edges[0], "target", "missing"), "missing_target"),
    (lambda b: setattr(b.missions[0], "entry", None), "missing_entry"),
    (lambda b: setattr(b.nodes[0], "text", "missing"), "missing_text"),
    (lambda b: setattr(b.nodes[0], "kind", "mystery"), "unknown_type"),
    (lambda b: setattr(b.edges[1], "condition", {"mystery": 1}), "invalid_condition"),
    (lambda b: b.nodes.append(Node("lonely", "m", "end")), "unreachable"),
    (lambda b: setattr(b.edges[0], "source", "missing"), "missing_target"),
])
def test_invalid_graph_diagnostics(graph, change, code):
    change(graph)
    assert code in {d["code"] for d in validate(graph)["diagnostics"]}


def test_duplicate_ids_reject_build(tmp_path, graph):
    graph.nodes.append(deepcopy(graph.nodes[0]))
    assert "duplicate_id" in {d["code"] for d in validate(graph)["diagnostics"]}
    with pytest.raises(ValueError, match="重复"): compile_story(graph, tmp_path / "bad.storypack")


def test_cycles_reported(graph):
    graph.edges.append(Edge("loop", "d", "a"))
    assert "possible_cycle" in {d["code"] for d in validate(graph)["diagnostics"]}


def test_no_end_path(graph):
    graph.edges[-1].target = "d"
    assert "no_end_path" in {d["code"] for d in validate(graph)["diagnostics"]}


def test_bounded_exploration(pack_path):
    with StoryPack(pack_path) as pack:
        result = explore(pack, "m")
        assert not result["blocked"] and not result["truncated"]
        assert len(result["choices_explored"]) == 2
        assert result["merged_states"] == 1
        assert explore(pack, "m", max_states=1)["truncated"]


def test_incomplete_branch_partial(tmp_path, graph):
    graph.nodes[2].kind = "unknown"
    report = compile_story(graph, tmp_path / "partial.storypack")
    assert report["missions"]["m"] == "PARTIAL"


def test_orphan_edges_survive_reopen(tmp_path, graph):
    graph.edges.append(Edge("orphan", "absent", "d"))
    path = tmp_path / "broken.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        assert "missing_target" in {d["code"] for d in validate(pack.bundle())["diagnostics"]}


def test_blocked_after_cosmetic_setup(graph):
    graph.nodes[0].kind = "noop"
    graph.nodes[1].kind = "unknown"
    assert validate(graph)["missions"]["m"] == "BLOCKED"


def test_definite_assignment_across_merge(graph):
    graph.nodes[2].kind = "set"; graph.nodes[2].data = {"var": "x", "value": 1}
    graph.edges[-1].condition = {"eq": [{"var": "x"}, 1]}
    assert "undefined_variable" in {d["code"] for d in validate(graph)["diagnostics"]}


def test_obviously_overlapping_conditions(graph):
    graph.nodes[1].kind = "branch"
    for e in graph.edges[1:3]: e.kind = "condition"; e.condition = True
    assert "ambiguous_condition" in {d["code"] for d in validate(graph)["diagnostics"]}
