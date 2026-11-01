"""Real Trailblaze performance verification; never substitute visitor coverage."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import pytest

from astralogue.compiler.hsr_mainline import MainlineCompiler
from astralogue.compiler import compile_story
from astralogue.runtime import BlockedEvent, ChoiceEvent, DiagnosticEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack

ACT = "Config/Level/Mission/1000201/Act/Act100020113.json"


@pytest.fixture(scope="module")
def real_mainline(tmp_path_factory):
    source = os.environ.get("ASTRALOGUE_HSR_MAINLINE_SOURCE")
    if not source: pytest.skip("设置 ASTRALOGUE_HSR_MAINLINE_SOURCE 以验证实际开拓任务片段")
    source = Path(source); root = tmp_path_factory.mktemp("real-mainline"); copy = root / "upstream"
    resources = ["source.json", "ExcelOutput/MainMission.json", "ExcelOutput/MainMissionType.json",
        "ExcelOutput/MissionChapterConfig.json", "ExcelOutput/TalkSentenceConfig.json", "ExcelOutput/PerformanceD.json",
        "TextMap/TextMapCHS.json", "TextMap/TextMapMainCHS.json",
        "Config/Level/Mission/1000202/MissionInfo_1000202.json",
        "Config/Level/Mission/1000202/MissionInfo_1000202.partial.json",
        "Config/Level/Mission/1000201/Mission_100020113.json", ACT]
    for rel in resources:
        original = source / rel
        if not original.is_file(): pytest.fail(f"真实主线测试资源缺失: {rel}")
        target = copy / rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(original, target)
    compiler = MainlineCompiler(copy); bundle = compiler.compile()
    controller = "Config/Level/Mission/1000201/Mission_100020113.json"
    candidates = [(mid, label) for mid, label in bundle.metadata["mission_labels"].items() if label.get("resource") == controller and label["scope"] == "SUBMISSION_FRAGMENT"]
    assert len(candidates) == 1
    fragment, label = candidates[0]
    assert label["parent"] == "hsr:mission:1000202"
    definition = next(m for m in compiler.manifest["missions"] if m["id"] == "1000202")
    assert definition["classification"]["value"] == "Main"
    assert any(s["id"] == "100020113" and s["resource"].endswith("Mission_100020113.json") for s in definition["submissions"])
    out = root / "mainline.storypack"; compile_story(bundle, out)
    assert copy.resolve().is_relative_to(root.resolve()); shutil.rmtree(copy)
    return out, fragment


def visible(rt):
    for _ in range(100):
        e = rt.next()
        if not isinstance(e, DiagnosticEvent): return e
    pytest.fail("too many automatic diagnostics")


@pytest.mark.parametrize("first,second", [(a, b) for a in ["1", "2"] for b in ["1", "2", "3"]])
def test_real_trailblaze_branch_ids_and_return(real_mainline, first, second, monkeypatch):
    path, mid = real_mainline
    def offline(*a, **kw): raise AssertionError("offline runtime attempted network")
    monkeypatch.setattr(socket.socket, "connect", offline)
    with StoryPack(path) as pack:
        rt = Runtime(pack, mid); ids = []; selections = iter([first, second])
        for _ in range(100):
            e = visible(rt)
            if isinstance(e, DialogueEvent): ids.append(pack.node(e.node).data["sentence_id"])
            elif isinstance(e, ChoiceEvent): rt.choose(next(selections))
            elif isinstance(e, EndEvent): break
            elif isinstance(e, BlockedEvent): pytest.fail(str(e))
        else: pytest.fail("mainline fragment did not terminate")
        expected = [100020329, 100020330] + ([100020332, 100020333] if first == "1" else [100020335, 100020336])
        expected += [100020337, 100020338, 100020339, 100020340, 100020341]
        expected += [100020345, 100020346] if second == "3" else [100020346]
        assert ids == expected
        assert rt.state.frames == []
        assert "hsr:finish:Mission_100020113" in rt.state.events


def test_real_mainline_save_and_rechoose(real_mainline, tmp_path):
    path, mid = real_mainline; save = tmp_path / "main.save.json"
    with StoryPack(path) as p:
        rt = Runtime(p, mid); assert visible(rt).node; assert visible(rt).node
        assert isinstance(visible(rt), ChoiceEvent); rt.choose("1")
        assert p.node(visible(rt).node).data["sentence_id"] == 100020332
        rt.save(save)
    with StoryPack(path) as p:
        rt = Runtime.load(p, save)
        assert p.node(visible(rt).node).data["sentence_id"] == 100020333
        rt.back(); assert isinstance(visible(rt), ChoiceEvent); rt.choose("2")
        assert p.node(visible(rt).node).data["sentence_id"] == 100020335


def test_real_mainline_cli_without_upstream(real_mainline, tmp_path):
    path, mid = real_mainline
    result = subprocess.run([sys.executable, "-m", "astralogue", "play", mid, "--pack", str(path),
                             "--autosave", str(tmp_path / "auto.json"), "--debug"],
                            input="\n\n1\n" + "\n" * 7 + "3\n\n\n\n", capture_output=True,
                            text=True, encoding="utf-8", timeout=20, cwd=tmp_path,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"})
    assert result.returncode == 0, result.stderr
    assert "本会话结束" in result.stdout
    assert "剧情暂停" not in result.stdout
    assert "主线子任务片段" in result.stdout
