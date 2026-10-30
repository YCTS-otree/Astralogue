"""Optional larger HSR corpus verification, separate from the small fixture."""
import os
from pathlib import Path
import pytest

from astralogue.adapters import import_source
from astralogue.compiler import compile_story
from astralogue.storypack import StoryPack
from astralogue.validation.explore import explore


def test_all_resolved_train_visitor_sessions(tmp_path):
    root = os.environ.get("ASTRALOGUE_HSR_BATCH_SOURCE")
    if not root: pytest.skip("设置 ASTRALOGUE_HSR_BATCH_SOURCE 以验证更大的崩铁集合")
    b = import_source(Path(root), ["CHS"], pattern="Config/Level/Mission/TrainVisitor/Act/*.json")
    out = tmp_path / "batch.storypack"
    report = compile_story(b, out)
    assert report["counts"].get("RESOLVED", 0) > 0
    with StoryPack(out) as p:
        for m in p.missions(status="RESOLVED"):
            result = explore(p, m["id"])
            assert not result["blocked"], (m["id"], result["blocked"])
            assert not result["truncated"], m["id"]
