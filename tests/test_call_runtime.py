import json
import pytest

from astralogue.compiler import compile_story
from astralogue.model import Edge, Mission, Node
from astralogue.runtime import DialogueEvent, Runtime
from astralogue.storypack import StoryPack


def test_cross_mission_call_return_and_save(graph, tmp_path):
    graph.missions[0].entry = "call"
    graph.missions.append(Mission("callee", "title", "callee-line"))
    graph.nodes.extend([Node("call", "m", "call"), Node("callee-line", "callee", "dialogue", "b"),
                        Node("return", "callee", "return")])
    graph.edges.extend([Edge("call-entry", "call", "callee-line", "call"), Edge("call-next", "call", "a"),
                        Edge("callee-next", "callee-line", "return"), Edge("ret", "return", "a", "return")])
    graph.metadata["required_capabilities"] = ["call-return-v1"]
    path = tmp_path / "call.storypack"; compile_story(graph, path)
    save = tmp_path / "call.save.json"
    with StoryPack(path) as p:
        rt = Runtime(p, "m")
        assert isinstance(rt.next(), DialogueEvent)
        assert rt.state.mission == "callee" and rt.state.frames[0]["return"] == "a"
        rt.save(save)
    with StoryPack(path) as p:
        rt = Runtime.load(p, save)
        assert rt.next().node == "a"
        assert rt.state.mission == "m" and rt.state.frames == []
        data = json.loads(save.read_text(encoding="utf-8")); data["state"]["frames"][0]["return"] = "b"
        save.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="返回地址"): Runtime.load(p, save)


def test_recursive_calls_are_bounded(graph, tmp_path):
    graph.nodes[0].kind = "call"
    graph.edges = [e for e in graph.edges if e.source != "a"]
    graph.edges += [Edge("recursive", "a", "a", "call"), Edge("continuation", "a", "end")]
    path = tmp_path / "recursive.storypack"; compile_story(graph, path)
    with StoryPack(path) as p:
        rt = Runtime(p, "m")
        assert rt.next().code == "call_depth"
        assert len(rt.state.frames) == 128


def test_import_time_preserved_without_changing_content_identity(graph, tmp_path):
    graph.metadata["imported_at_utc"] = "first"
    one = tmp_path / "one.storypack"; r1 = compile_story(graph, one)
    graph.metadata["imported_at_utc"] = "second"
    two = tmp_path / "two.storypack"; r2 = compile_story(graph, two)
    assert r1["pack_id"] == r2["pack_id"]
    with StoryPack(two) as p: assert p.metadata["imported_at_utc"] == "second"


def test_unknown_required_capability_is_rejected(graph, tmp_path):
    graph.metadata["required_capabilities"] = ["future-unsupported"]
    path = tmp_path / "future.storypack"; compile_story(graph, path)
    with pytest.raises(ValueError, match="执行能力"): StoryPack(path)
