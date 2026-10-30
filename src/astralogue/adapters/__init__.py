"""Build-time adapters. The runtime never imports this package."""
from pathlib import Path

from astralogue.model import Bundle, load_json


def discover(path: Path) -> str:
    if path.is_dir() and (path / "ExcelOutput/TalkSentenceConfig.json").is_file():
        return "hsr"
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}: return "browser-sqlite"
    if path.suffix.lower() == ".jsonl": return "starrail-jsonl"
    if path.suffix.lower() == ".json":
        obj = load_json(path)
        return "ir" if isinstance(obj, dict) and "ir_version" in obj else "starrail-json"
    raise ValueError(f"未识别数据源: {path}")


def import_source(path: Path, languages: list[str], adapter: str = "auto", pattern: str | None = None) -> Bundle:
    kind = discover(path) if adapter == "auto" else adapter
    if kind == "ir": return Bundle.from_dict(load_json(path))
    if kind == "hsr":
        from .hsr import HsrAdapter
        return HsrAdapter(path, languages).load(pattern)
    if kind in {"starrail-jsonl", "starrail-json", "browser-sqlite"}:
        from .extracted import load_extracted
        return load_extracted(path, languages[0], kind)
    raise ValueError(f"未知 Adapter: {kind}")
