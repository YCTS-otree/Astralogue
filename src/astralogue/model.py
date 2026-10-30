"""Versioned interchange format. All control flow lives in explicit edges."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
IR_VERSION = 1
KINDS = {"dialogue", "choice", "branch", "set", "emit", "wait", "enter", "exit", "end", "unknown", "noop"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass
class Node:
    id: str
    mission: str
    kind: str
    text: str | None = None
    speaker: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    id: str
    source: str
    target: str
    kind: str = "next"
    text: str | None = None
    condition: Any = None
    value: str | None = None


@dataclass
class Mission:
    id: str
    title: str
    entry: str | None
    chapter: str = "default"
    original_id: str | None = None


@dataclass
class Diagnostic:
    code: str
    message: str
    severity: str = "warning"
    mission: str | None = None
    node: str | None = None


@dataclass
class Bundle:
    ir_version: int = IR_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)
    chapters: dict[str, str] = field(default_factory=lambda: {"default": "default-title"})
    missions: list[Mission] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    texts: dict[str, dict[str, str]] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> Bundle:
        if obj.get("ir_version") != IR_VERSION:
            raise ValueError("不支持的 IR 版本")
        b = cls(**{k: v for k, v in obj.items() if k not in {"nodes", "edges", "missions", "diagnostics"}})
        b.nodes = [Node(**x) for x in obj.get("nodes", [])]
        b.edges = [Edge(**x) for x in obj.get("edges", [])]
        b.missions = [Mission(**x) for x in obj.get("missions", [])]
        b.diagnostics = [Diagnostic(**x) for x in obj.get("diagnostics", [])]
        return b

    def text(self, key: str, value: str, lang: str = "CHS") -> str:
        previous = self.texts.setdefault(key, {}).get(lang)
        if previous is not None and previous != value:
            raise ValueError(f"文本冲突: {key}/{lang}")
        self.texts[key][lang] = value
        return key


def load_json(path: Path) -> Any:
    # Duplicate JSON keys must not disappear during deserialization.
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"重复 JSON 字段: {k} ({path.name})")
            result[k] = v
        return result

    with path.open(encoding="utf-8-sig") as f:
        return json.load(f, object_pairs_hook=unique)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
