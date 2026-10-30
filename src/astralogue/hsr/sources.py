"""Version-aware, content-addressed resource resolution with explicit conflicts."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from astralogue.model import file_hash, load_json


class ResourceError(ValueError):
    pass


class Sources:
    def __init__(self, roots: list[Path]):
        self.roots = [p.resolve() for p in roots]
        self.versions = [load_json(p / "source.json") if (p / "source.json").is_file() else {"revision": "unknown"} for p in self.roots]
        if any(not isinstance(source, dict) for source in self.versions): raise ResourceError("source.json 必须是对象")
        self.versions = [{k: v for k, v in source.items() if k not in {"files", "resource_index"}} for source in self.versions]
        self.inputs: dict[str, str] = {}
        self.records: dict[str, dict] = {}
        self.conflicts: list[dict] = []
        self.cache: dict[str, Any] = {}
        self.timeline_index = {}
        self.timeline_conflicts = set()
        for priority, root in enumerate(self.roots):
            p = root / "timeline-index.json"
            if p.is_file():
                obj = load_json(p)
                if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
                    raise ResourceError("Timeline 索引必须为逻辑名到相对路径的映射")
                sha = file_hash(p)
                self.inputs[f"source{priority}:timeline-index.json"] = sha
                self.records[f"timeline-index:source{priority}"] = {"file": "timeline-index.json", "sha256": sha, "source": self.versions[priority], "priority": priority, "raw": obj}
                verified = priority == 0 or (self.versions[0].get("revision") not in {None, "unknown"} and self.versions[priority].get("revision") == self.versions[0].get("revision"))
                for logical, resource in obj.items():
                    if not verified:
                        self.timeline_conflicts.add(logical)
                        self.conflicts.append({"kind": "timeline_index_revision", "name": logical, "source": self.versions[priority]})
                        continue
                    if logical in self.timeline_index and self.timeline_index[logical] != resource:
                        self.timeline_conflicts.add(logical)
                        self.conflicts.append({"kind": "timeline_index_mapping", "name": logical, "candidates": [self.timeline_index[logical], resource]})
                        continue
                    self.timeline_index[logical] = resource

    def path(self, root: Path, logical: str) -> Path:
        rel = PurePosixPath(logical)
        forbidden = {".ssh", ".aws", ".git", ".codex", ".agents", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
        if any(part in forbidden for part in rel.parts) or rel.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            raise ResourceError("路径不是可读取的剧情资源")
        if rel.is_absolute() or ".." in rel.parts or "\\" in logical or ":" in logical:
            raise ResourceError(f"资源路径越界: {logical}")
        path = (root / logical).resolve()
        if not path.is_relative_to(root): raise ResourceError(f"资源链接越界: {logical}")
        return path

    def exists(self, logical: str) -> bool:
        return any(self.path(root, logical).is_file() for root in self.roots)

    def read(self, logical: str) -> Any:
        if logical in self.cache: return self.cache[logical]
        candidates = []
        for priority, root in enumerate(self.roots):
            path = self.path(root, logical)
            if path.is_file():
                candidates.append({"priority": priority, "path": path, "hash": file_hash(path), "source": self.versions[priority]})
        if not candidates: raise ResourceError(f"资源缺失: {logical}")
        versions = {c["source"].get("game_version") for c in candidates if c["source"].get("game_version")}
        if len({c["hash"] for c in candidates}) > 1 or len(versions) > 1:
            conflict = {"logical_path": logical, "candidates": [{k: v for k, v in c.items() if k != "path"} for c in candidates]}
            self.conflicts.append(conflict)
            raise ResourceError(f"多来源资源/版本冲突: {logical}")
        chosen = candidates[0]
        if chosen["priority"] > 0:
            expected = self.versions[0].get("revision")
            if expected in {None, "unknown"} or chosen["source"].get("revision") != expected:
                conflict = {"logical_path": logical, "reason": "supplement revision does not match the primary",
                            "primary": self.versions[0], "candidate": chosen["source"]}
                self.conflicts.append(conflict)
                raise ResourceError(f"补充资源版本未验证: {logical}")
        with chosen["path"].open("rb") as f: header = f.read(16)
        if not header.lstrip().startswith((b"{", b"[", b"\xef\xbb\xbf")):
            raise ResourceError(f"非明文 JSON 控制资源（不解密）: {logical}, magic={header[:4].hex()}")
        value = load_json(chosen["path"])
        self.inputs[f"source{chosen['priority']}:{logical}"] = chosen["hash"]
        self.records[logical] = {"file": logical, "sha256": chosen["hash"], "source": chosen["source"], "priority": chosen["priority"], "raw": value}
        self.cache[logical] = value
        return value

    def timeline(self, name: str) -> tuple[str, dict]:
        # No guessed extension, transcript ID ordering, or unverified track names.
        if name in self.timeline_conflicts: raise ResourceError(f"Timeline 索引版本/映射冲突: {name}")
        logical = self.timeline_index.get(name, name)
        obj = self.read(logical)
        if not isinstance(obj, dict) or not isinstance(obj.get("OnStartSequece"), list):
            raise ResourceError(f"Timeline 序列化格式未知: {name}")
        return logical, obj


def performance_index(sources: Sources) -> dict[tuple[str, str], set[str]]:
    mapping = {}
    for name, kind in [("PerformanceA", "A"), ("PerformanceC", "C"), ("PerformanceD", "D"),
                       ("PerformanceDS", "D"), ("PerformanceE", "E"), ("PerformanceVideo", "PlayVideo")]:
        rel = "ExcelOutput/" + name + ".json"
        if not sources.exists(rel): continue
        obj = sources.read(rel)
        for row in obj.values() if isinstance(obj, dict) else obj:
            if "PerformanceID" in row and "PerformancePath" in row:
                mapping.setdefault((kind, str(row["PerformanceID"])), set()).add(row["PerformancePath"])
    return mapping
