import json
import pytest

from astralogue.compiler import compile_story
from astralogue.model import Edge, Mission, Node
from astralogue.runtime import BlockedEvent, ChoiceEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack


def test_sequential_dialogue(tmp_path, graph):
    graph.edges[0].target = "d"
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m")
        assert [rt.next().node, rt.next().node] == ["a", "d"]
        assert isinstance(rt.next(), EndEvent)


@pytest.mark.parametrize("value,branch", [("first", "b"), ("second", "c")])
def test_branch_and_merge(pack_path, value, branch):
    with StoryPack(pack_path) as pack:
        rt = Runtime(pack, "m")
        assert rt.next().node == "a"
        c = rt.next(); assert isinstance(c, ChoiceEvent)
        assert rt.next() == c
        rt.choose(value)
        assert rt.next().node == branch
        assert rt.next().node == "d"
        assert isinstance(rt.next(), EndEvent)


def test_single_option(tmp_path, graph):
    graph.edges = [e for e in graph.edges if e.id != "p-c"]
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); rt.next()
        assert len(rt.next().options) == 1
        with pytest.raises(ValueError): rt.choose("second")
        rt.choose("first"); assert rt.next().node == "b"


def test_two_options_same_target(tmp_path, graph):
    graph.edges[2].target = "b"
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); rt.next(); event = rt.next()
        assert len(event.options) == 2
        assert event.options[0].target == event.options[1].target
        rt.choose("second"); assert rt.next().node == "b"


def test_variables_conditions_and_events(tmp_path, graph):
    graph.nodes.extend([Node("set", "m", "set", data={"var": "x", "value": 2}),
                        Node("add", "m", "set", data={"var": "x", "op": "add", "value": 1}),
                        Node("branch", "m", "branch"), Node("emit", "m", "emit", data={"event": "ready"}),
                        Node("wait", "m", "wait", data={"event": "ready", "consume": True})])
    graph.missions[0].entry = "set"
    yes = {"all": [{"eq": [{"var": "x"}, 3]}, {"event": "ready"}]}
    graph.edges.extend([Edge("s-a", "set", "add"), Edge("a-em", "add", "emit"), Edge("em-b", "emit", "branch"),
                        Edge("yes", "branch", "wait", "condition", condition=yes),
                        Edge("no", "branch", "c", "condition", condition={"not": yes}), Edge("w-a", "wait", "a")])
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m")
        assert rt.next().node == "a"
        assert rt.state.variables == {"x": 3}
        assert rt.state.events == []


def test_conditional_options(tmp_path, graph):
    graph.edges[1].condition = False
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); rt.next()
        assert [o.value for o in rt.next().options] == ["second"]
        with pytest.raises(ValueError): rt.choose("first")


@pytest.mark.parametrize("expr", [{"python": "print('no')"}, {"eq": [{"var": "undefined"}, 1]}])
def test_unsupported_or_unset_condition_blocks(tmp_path, graph, expr):
    graph.edges[1].condition = expr
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); rt.next()
        assert isinstance(rt.next(), BlockedEvent)
        with pytest.raises(ValueError): rt.choose("first")


def test_ambiguous_condition_blocks(tmp_path, graph):
    graph.nodes[1].kind = "branch"
    for edge in graph.edges[1:3]: edge.kind = "condition"; edge.condition = True
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m"); rt.next()
        assert rt.next().code == "ambiguous_condition"


@pytest.mark.parametrize("kind", ["unknown", "future_extension"])
def test_unknown_blocks(tmp_path, graph, kind):
    graph.nodes[0].kind = kind
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        event = Runtime(pack, "m").next()
        assert isinstance(event, BlockedEvent)
        assert event.node == "a"


def test_wait_and_signal(tmp_path, graph):
    graph.nodes.insert(0, Node("w", "m", "wait", data={"event": "go", "consume": True}))
    graph.edges.insert(0, Edge("w-a", "w", "a")); graph.missions[0].entry = "w"
    path = tmp_path / "s.storypack"; compile_story(graph, path)
    with StoryPack(path) as pack:
        rt = Runtime(pack, "m")
        assert rt.next().code == "waiting_event"
        rt.signal("go"); assert rt.next().node == "a"
        assert rt.state.events == []


def test_save_restore_and_back(pack_path, tmp_path):
    save = tmp_path / "save.json"
    with StoryPack(pack_path) as pack:
        rt = Runtime(pack, "m"); rt.next(); rt.next()
        rt.state.variables["before"] = 7; rt.signal("prior")
        checkpoint = rt.snapshot()
        rt.choose("first"); assert rt.next().node == "b"
        rt.state.variables["before"] = 99; rt.signal("after")
        rt.save(save)
        rt = Runtime.load(pack, save)
        assert rt.next().node == "d"
        rt.back()
        assert rt.snapshot() == checkpoint
        rt.choose("second"); assert rt.next().node == "c"
        assert len(rt.state.choices) == 1
        with pytest.raises(ValueError): rt.choose("first")


def test_save_before_choice(pack_path, tmp_path):
    with StoryPack(pack_path) as pack:
        rt = Runtime(pack, "m"); rt.next(); c = rt.next()
        dest = tmp_path / "save.json"; rt.save(dest)
        assert Runtime.load(pack, dest).next() == c


def test_pack_update_refuses_old_save(pack_path, tmp_path, graph):
    dest = tmp_path / "save.json"
    with StoryPack(pack_path) as pack: Runtime(pack, "m").save(dest)
    graph.metadata["version"] = "1.0.1"
    newer = tmp_path / "new.storypack"; compile_story(graph, newer)
    with StoryPack(newer) as pack:
        with pytest.raises(ValueError, match="不兼容"): Runtime.load(pack, dest)


def test_corrupted_save(pack_path, tmp_path):
    dest = tmp_path / "save.json"
    with StoryPack(pack_path) as pack:
        Runtime(pack, "m").save(dest)
        obj = json.loads(dest.read_text(encoding="utf-8")); obj["state"]["node"] = "missing"
        dest.write_text(json.dumps(obj), encoding="utf-8")
        with pytest.raises(ValueError): Runtime.load(pack, dest)


def test_auto_loop_is_bounded(tmp_path, graph):
    graph.nodes[0].kind = "noop"; graph.edges[0].target = "a"
    dest = tmp_path / "loop.storypack"; compile_story(graph, dest)
    with StoryPack(dest) as pack:
        assert Runtime(pack, "m").next().code == "auto_loop"


def test_cross_mission_context(tmp_path, graph):
    graph.nodes.extend([Node("enter", "m", "enter"), Node("sub", "sub", "dialogue", "b"), Node("exit", "sub", "exit")])
    graph.missions.append(Mission("sub", "title", "sub")); graph.missions[0].entry = "enter"
    graph.edges.extend([Edge("en-s", "enter", "sub"), Edge("sub-ex", "sub", "exit"), Edge("ex-a", "exit", "a")])
    dest = tmp_path / "cross.storypack"; compile_story(graph, dest)
    with StoryPack(dest) as pack:
        rt = Runtime(pack, "m"); assert rt.next().node == "sub"
        assert rt.state.mission == "sub" and rt.state.context == ["m"]
        save = tmp_path / "context.json"; rt.save(save); rt = Runtime.load(pack, save)
        assert rt.next().node == "a"
        assert rt.state.mission == "m" and rt.state.context == []
