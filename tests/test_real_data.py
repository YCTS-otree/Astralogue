"""Integration against locally acquired, pinned real game data; no game text in Git."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import pytest

from astralogue.adapters import import_source
from astralogue.compiler import compile_story
from astralogue.fetch import FILES
from astralogue.runtime import BlockedEvent, ChoiceEvent, DiagnosticEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack
from astralogue.validation.explore import explore

ACT = "Config/Level/Mission/TrainVisitor/Act/Act500100101.json"
MID = "hsr:" + ACT.removesuffix(".json")


@pytest.fixture(scope="module")
def real_pack(tmp_path_factory):
    source = os.environ.get("ASTRALOGUE_HSR_SOURCE")
    if not source: pytest.skip("设置 ASTRALOGUE_HSR_SOURCE 后执行真实数据测试")
    source = Path(source)
    for rel in FILES:
        if not (source / rel).is_file(): pytest.fail(f"真实测试资源缺失: {rel}")
    temp = tmp_path_factory.mktemp("real-hsr")
    upstream = temp / "upstream"
    for rel in FILES:
        dest = upstream / rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source / rel, dest)
    if (source / "source.json").is_file(): shutil.copyfile(source / "source.json", upstream / "source.json")
    bundle = import_source(upstream, ["CHS"], pattern=ACT)
    out = temp / "real.storypack"
    report = compile_story(bundle, out)
    assert report["missions"][MID] == "RESOLVED"
    # Remove only the disposable copy owned by this test, never user data.
    assert upstream.resolve().is_relative_to(temp.resolve())
    shutil.rmtree(upstream)
    assert not upstream.exists()
    return out


def walk(rt, first):
    sentences, choices = [], 0
    for _ in range(100):
        event = rt.next()
        if isinstance(event, DialogueEvent): sentences.append(rt.pack.node(event.node).data["sentence_id"])
        elif isinstance(event, ChoiceEvent):
            rt.choose(first if choices == 0 else "1"); choices += 1
        elif isinstance(event, EndEvent): return sentences, choices
        elif isinstance(event, BlockedEvent): pytest.fail(f"真实剧情阻塞: {event}")
    pytest.fail("真实剧情超出执行上限")


def test_real_branches_merge_after_upstream_removed(real_pack, monkeypatch):
    def no_network(*args, **kwargs): raise AssertionError("离线运行时发生网络访问")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    with StoryPack(real_pack) as pack:
        left, lc = walk(Runtime(pack, MID), "1")
        right, rc = walk(Runtime(pack, MID), "2")
        assert left == [500100102, 500100103, 500100105, 500100106, 500100110, 500100112, 500100113, 500100114]
        assert right == [500100102, 500100103, 500100108, 500100109, 500100110, 500100112, 500100113, 500100114]
        assert lc == rc == 2
        result = explore(pack, MID)
        assert not result["truncated"] and not result["blocked"]
        assert len(result["choices_explored"]) == 3


def test_real_save_restore_and_rechoose(real_pack, tmp_path):
    with StoryPack(real_pack) as pack:
        rt = Runtime(pack, MID)
        for _ in range(30):
            if isinstance(rt.next(), ChoiceEvent): break
        else: pytest.fail("未遇到真实选择")
        rt.choose("1")
        for _ in range(30):
            event = rt.next()
            if isinstance(event, DialogueEvent): break
        assert pack.node(event.node).data["sentence_id"] == 500100105
        save = tmp_path / "real.save.json"; rt.save(save)
    with StoryPack(real_pack) as pack:
        rt = Runtime.load(pack, save)
        assert pack.node(rt.next().node).data["sentence_id"] == 500100106
        rt.back(); assert isinstance(rt.next(), ChoiceEvent)
        remaining, choices = walk(rt, "2")
        assert remaining == [500100108, 500100109, 500100110, 500100112, 500100113, 500100114]


def test_real_cli_in_fresh_process_without_sources(real_pack, tmp_path):
    result = subprocess.run([sys.executable, "-m", "astralogue", "play", MID, "--pack", str(real_pack),
                             "--autosave", str(tmp_path / "auto.json")],
                            input="\n\n2\n\n\n\n1\n\n\n\n\n", text=True, encoding="utf-8",
                            capture_output=True, cwd=tmp_path, timeout=20,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"})
    assert result.returncode == 0, result.stderr
    assert "本会话结束" in result.stdout
    assert "剧情暂停" not in result.stdout
    assert "【" in result.stdout and "1." in result.stdout and "2." in result.stdout
