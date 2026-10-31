"""Persistent build-only native maps; immutable runs are imported once."""
import json
from pathlib import Path
import sqlite3

from astralogue.model import file_hash
from .animestudio import load_map


class NativeIndex:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(hash TEXT PRIMARY KEY, path TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS blocks(version TEXT, name TEXT, sha256 TEXT, bytes INTEGER,
          PRIMARY KEY(version,name));
        CREATE TABLE IF NOT EXISTS assets(block_sha TEXT, offset INTEGER, path_id TEXT, type TEXT,
          container TEXT, record TEXT, PRIMARY KEY(block_sha,offset,path_id,type,container));
        """)
    def close(self): self.db.close()
    def processed(self, version: str) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT name FROM blocks WHERE version=?", (version,))}
    def remaining(self, paths: list[Path]) -> list[Path]:
        """Reuse a map only when current block bytes still have an indexed SHA256."""
        known = {}
        for name, sha, size in self.db.execute("SELECT name,sha256,bytes FROM blocks"):
            known.setdefault((name, size), set()).add(sha)
        remaining = []
        for path in paths:
            hashes = known.get((path.name, path.stat().st_size), set())
            if not hashes or file_hash(path) not in hashes: remaining.append(path)
        return remaining
    def ingest(self, staging: Path) -> dict:
        added, rejected = 0, []
        for path in sorted(staging.glob("*/run.json")):
            sha = file_hash(path)
            if self.db.execute("SELECT 1 FROM runs WHERE hash=?", (sha,)).fetchone(): continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if "outputs" not in record or "--map_op" not in record.get("command", []): continue
            if record.get("timed_out") or record.get("returncode") != 0: continue
            log = (path.parent / "tool.log").read_text(encoding="utf-8", errors="replace")
            if "[Error]" in log or "[Warning]" in log:
                rejected.append(path.parent.name); continue
            mp = path.parent / "output/assets_map.json"
            if not mp.is_file(): continue
            if not any(o["path"] == "output/assets_map.json" and o["sha256"] == file_hash(mp)
                       for o in record["outputs"]):
                raise ValueError("Asset Map changed after finalized run")
            entries = load_map(mp)
            sources = {Path(x["staged"].replace("\\", "/")).name: x for x in record["inputs"]}
            version = record.get("game_manifest_sha256") or record["game_version"]
            with self.db:
                for name, x in sources.items():
                    old = self.db.execute("SELECT sha256 FROM blocks WHERE version=? AND name=?", (version, name)).fetchone()
                    row_version = version if not old or old[0] == x["sha256"] else version + ":block:" + x["sha256"]
                    self.db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?,?)", (row_version, name, x["sha256"], x["bytes"]))
                for entry in entries:
                    source = sources[Path(entry["Source"].replace("\\", "/")).name]
                    self.db.execute("INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?,?)", (
                        source["sha256"], entry.get("Offset", 0), str(entry["PathID"]), entry["Type"],
                        entry["Container"], json.dumps(entry, ensure_ascii=False)))
                self.db.execute("INSERT INTO runs VALUES(?,?)", (sha, str(path)))
            added += 1
        return {"new_runs": added, "blocks": self.db.execute("SELECT count(*) FROM blocks").fetchone()[0],
                "assets": self.db.execute("SELECT count(*) FROM assets").fetchone()[0], "rejected_runs": rejected}
