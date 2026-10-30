"""Standalone, deterministic SQLite packaging and read-only access."""
from __future__ import annotations

from dataclasses import asdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from astralogue import __version__
from astralogue.model import Bundle, Diagnostic, Edge, Mission, Node, SCHEMA_VERSION, canonical, digest

DDL = """
PRAGMA user_version=1;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE chapters(id TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE missions(id TEXT PRIMARY KEY, title TEXT NOT NULL, entry TEXT, chapter TEXT NOT NULL, original_id TEXT, status TEXT NOT NULL);
CREATE TABLE nodes(id TEXT PRIMARY KEY, mission TEXT NOT NULL, kind TEXT NOT NULL, text TEXT, speaker TEXT, data TEXT NOT NULL);
CREATE TABLE edges(id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL, text TEXT, condition TEXT, value TEXT);
CREATE INDEX edges_source ON edges(source);
CREATE INDEX nodes_mission ON nodes(mission);
CREATE TABLE texts(id TEXT NOT NULL, lang TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(id,lang));
CREATE TABLE source_refs(id INTEGER PRIMARY KEY, node TEXT, file TEXT, pointer TEXT, record TEXT NOT NULL);
CREATE TABLE diagnostics(id INTEGER PRIMARY KEY, origin TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL, severity TEXT NOT NULL, mission TEXT, node TEXT);
"""


def write_pack(bundle: Bundle, output: Path, report: dict, force: bool = False) -> str:
    if output.exists() and not force: raise ValueError(f"文件已存在，使用 --force 明确覆盖: {output}")
    if any(d["code"] == "duplicate_id" for d in report["diagnostics"]): raise ValueError("重复 ID，拒绝构建；请先解决冲突")
    # Canonical logical identity includes source hashes, language maps and raw
    # unsupported operations. Reordering independent IR records is immaterial.
    obj = bundle.to_dict()
    for key in ["nodes", "edges", "missions"]: obj[key].sort(key=lambda x: x["id"])
    obj["source_refs"].sort(key=canonical)
    obj["diagnostics"].sort(key=canonical)
    identity = digest({"schema": SCHEMA_VERSION, "compiler": __version__, "bundle": obj, "validation_language": report["language"]})
    meta = {**bundle.metadata, "pack_id": identity, "pack_version": bundle.metadata.get("version", "1.0.0"),
            "schema_version": SCHEMA_VERSION, "engine_version": __version__, "validation_language": report["language"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".building-", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with closing(sqlite3.connect(temp_path)) as con, con:
            con.executescript(DDL)
            con.executemany("INSERT INTO metadata VALUES (?,?)", [(k, canonical(v)) for k, v in sorted(meta.items())])
            con.executemany("INSERT INTO chapters VALUES (?,?)", sorted(bundle.chapters.items()))
            con.executemany("INSERT INTO missions VALUES (?,?,?,?,?,?)", [(m.id, m.title, m.entry, m.chapter, m.original_id, report["missions"][m.id]) for m in sorted(bundle.missions, key=lambda m: m.id)])
            con.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?)", [(n.id, n.mission, n.kind, n.text, n.speaker, canonical(n.data)) for n in sorted(bundle.nodes, key=lambda n: n.id)])
            con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", [(e.id, e.source, e.target, e.kind, e.text, canonical(e.condition) if e.condition is not None else None, e.value) for e in sorted(bundle.edges, key=lambda e: e.id)])
            con.executemany("INSERT INTO texts VALUES (?,?,?)", [(k, lang, v) for k, langs in sorted(bundle.texts.items()) for lang, v in sorted(langs.items())])
            con.executemany("INSERT INTO source_refs VALUES (?,?,?,?,?)", [(i, r.get("node"), r.get("file"), r.get("pointer"), canonical(r)) for i, r in enumerate(obj["source_refs"])])
            upstream = {canonical(asdict(d)) for d in bundle.diagnostics}
            con.executemany("INSERT INTO diagnostics VALUES (?,?,?,?,?,?,?)", [(i, "source" if canonical(d) in upstream else "validation", d["code"], d["message"], d["severity"], d["mission"], d["node"]) for i, d in enumerate(sorted(report["diagnostics"], key=canonical))])
        # Close DB before atomic replacement (also required on Windows).
        if output.exists() and not force: raise ValueError("输出文件已在构建期间创建")
        temp_path.replace(output)
    finally:
        temp_path.unlink(missing_ok=True)
    return identity


class StoryPack:
    def __init__(self, path: Path):
        self.path = path
        self.con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        try:
            version = self.con.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION: raise ValueError(f"不支持的 StoryPack Schema {version}；需要显式迁移")
            self.metadata = {r["key"]: json.loads(r["value"]) for r in self.con.execute("SELECT * FROM metadata")}
            if self.metadata.get("schema_version") != version: raise ValueError("Schema 版本元数据不一致")
            if not isinstance(self.metadata.get("pack_id"), str): raise ValueError("缺少数据包标识")
        except Exception:
            self.close(); raise

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): self.con.close()

    def text(self, key: str | None, lang: str, fallback: str | None = None) -> str:
        if key is None:
            if fallback is not None: return fallback
            raise ValueError("缺少文本引用")
        row = self.con.execute("SELECT value FROM texts WHERE id=? AND lang=?", (key, lang)).fetchone()
        if row is None: raise ValueError(f"缺少文本: {key}/{lang}")
        return row[0]

    def mission(self, mid: str) -> dict:
        row = self.con.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if row is None: raise ValueError(f"未知任务: {mid}")
        return dict(row)

    def missions(self, search: str = "", chapter: str | None = None, lang: str = "CHS", status: str | None = None) -> list[dict]:
        results = []
        for row in self.con.execute("SELECT * FROM missions ORDER BY id"):
            item = dict(row)
            if status is not None and item["status"] != status: continue
            item["name"] = self.text(item["title"], lang)
            if (chapter is None or chapter == item["chapter"]) and (search.casefold() in item["name"].casefold() or search in item["id"]): results.append(item)
        return results

    def node(self, nid: str) -> Node:
        row = self.con.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
        if row is None: raise ValueError(f"缺少节点: {nid}")
        d = dict(row); d["data"] = json.loads(d["data"])
        return Node(**d)

    def edges(self, nid: str) -> list[Edge]:
        out = []
        for row in self.con.execute("SELECT * FROM edges WHERE source=? ORDER BY id", (nid,)):
            d = dict(row); d["condition"] = json.loads(d["condition"]) if d["condition"] is not None else None
            out.append(Edge(**d))
        return out

    def bundle(self) -> Bundle:
        b = Bundle(metadata=self.metadata)
        b.chapters = {r["id"]: r["title"] for r in self.con.execute("SELECT * FROM chapters ORDER BY id")}
        b.missions = [Mission(**{k: r[k] for k in ["id", "title", "entry", "chapter", "original_id"]}) for r in self.con.execute("SELECT * FROM missions ORDER BY id")]
        b.nodes = [self.node(r[0]) for r in self.con.execute("SELECT id FROM nodes ORDER BY id")]
        for row in self.con.execute("SELECT * FROM edges ORDER BY id"):
            d = dict(row); d["condition"] = json.loads(d["condition"]) if d["condition"] is not None else None
            b.edges.append(Edge(**d))
        for row in self.con.execute("SELECT * FROM texts ORDER BY id,lang"): b.text(row["id"], row["value"], row["lang"])
        b.source_refs = [json.loads(r[0]) for r in self.con.execute("SELECT record FROM source_refs ORDER BY id")]
        # Only upstream diagnostics are rechecked; generated diagnostics are not
        # fed into validation again, so repeated validation stays stable.
        b.diagnostics = [Diagnostic(**dict(r)) for r in self.con.execute("SELECT code,message,severity,mission,node FROM diagnostics WHERE origin='source' ORDER BY id")]
        return b
