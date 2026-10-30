from pathlib import Path
import pytest

from astralogue.compiler import compile_story
from astralogue.model import Bundle, Edge, Mission, Node


@pytest.fixture
def graph():
    """Abstract structural labels, not fictional game-story replacement."""
    b = Bundle(metadata={"version": "1.0.0", "languages": ["CHS", "EN"]})
    b.text("default-title", "结构测试")
    b.text("title", "测试会话"); b.text("title", "Test session", "EN")
    b.missions = [Mission("m", "title", "a")]
    for key in ["a", "b", "c", "d", "o1", "o2", "speaker"]:
        b.text(key, f"测试 {key} [literal]")
        b.text(key, f"Test {key}", "EN")
    b.nodes = [Node("a", "m", "dialogue", "a", "speaker"), Node("pick", "m", "choice"),
               Node("b", "m", "dialogue", "b", "speaker"), Node("c", "m", "dialogue", "c", "speaker"),
               Node("d", "m", "dialogue", "d", "speaker"), Node("end", "m", "end")]
    b.edges = [Edge("a-p", "a", "pick"), Edge("p-b", "pick", "b", "option", "o1", value="first"),
               Edge("p-c", "pick", "c", "option", "o2", value="second"), Edge("b-d", "b", "d"),
               Edge("c-d", "c", "d"), Edge("d-e", "d", "end")]
    return b


@pytest.fixture
def pack_path(tmp_path: Path, graph):
    path = tmp_path / "test.storypack"
    compile_story(graph, path)
    return path
