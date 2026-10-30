"""Compile canonical IR to a self-contained StoryPack."""
from pathlib import Path

from astralogue.model import Bundle
from astralogue.storypack import write_pack
from astralogue.validation import validate


def compile_story(bundle: Bundle, output: Path, lang: str = "CHS", force: bool = False) -> dict:
    report = validate(bundle, lang)
    report["pack_id"] = write_pack(bundle, output, report, force)
    return report
