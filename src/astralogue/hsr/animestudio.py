"""Bounded, build-only AnimeStudio bridge. All tool inputs are staged copies."""
from __future__ import annotations

from collections import Counter
import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any

from astralogue.model import file_hash

PARSER_VERSION = "animestudio-map-v1"
ASSET_TYPES = ("TextAsset", "MonoBehaviour", "PlayableDirector", "MonoScript")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_map(path: Path) -> list[dict]:
    """Read the observed CLI JSON schema, retaining unknown metadata verbatim."""
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("GameType") != "SR":
        raise ValueError("Asset Map must declare GameType SR")
    entries = obj.get("AssetEntries")
    if not isinstance(entries, list):
        raise ValueError("AssetEntries must be a list")
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("PathID"), int):
            raise ValueError("Asset entry has no integer PathID")
        if not all(isinstance(item.get(k), str) for k in ("Name", "Container", "Source", "Type")):
            raise ValueError("Malformed asset entry")
    return entries


def normalize_resource(value: str) -> str:
    value = value.replace("\\", "/").casefold()
    while "//" in value: value = value.replace("//", "/")
    if value.startswith("./"): value = value[2:]
    if value.startswith("assets/asbres/"): value = value[len("assets/asbres/"):]
    if ".." in value.split("/") or ":" in value: raise ValueError("Invalid logical resource path")
    return value


def timeline_matches(entries: list[dict], names: list[str]) -> dict[str, list[dict]]:
    """Exact asset basename matching; no substring/ID/order-based links."""
    result = {name: [] for name in names}
    normalized = {normalize_resource(name): name for name in names}
    short = {key for key in normalized if "/" not in key}
    for item in entries:
        try: container = normalize_resource(item["Container"])
        except ValueError: continue
        hits = {item["Name"].casefold(), PurePosixPath(container).stem} & short
        if container in normalized: hits.add(container)
        for hit in hits: result[normalized[hit]].append(item)
    return result


def native_coverage(staging: Path, baseline_ir: Path) -> dict:
    baseline = json.loads(baseline_ir.read_text(encoding="utf-8"))
    meta = baseline["metadata"]
    refs = [ref for mission in meta["hsr_metrics"].values() for ref in mission.get("timeline_references", [])]
    names = sorted({ref["name"] for ref in refs if isinstance(ref.get("name"), str)})
    asset_count, runs, rejected, blocks = 0, [], [], set()
    matches = {name: [] for name in names}
    version = meta["source"].get("game_version")
    for path in sorted(staging.glob("*/run.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "outputs" not in record:
            rejected.append({"run": path.parent.name, "reason": "run not finalized"}); continue
        if not version or record.get("game_version") != version:
            rejected.append({"run": path.parent.name, "reason": "game version mismatch"}); continue
        runs.append(path.parent.name)
        if "--map_op" not in record.get("command", []): continue
        map_path = path.parent / "output/assets_map.json"
        if not map_path.is_file(): continue
        entries = load_map(map_path)
        asset_count += len(entries)
        for name, items in timeline_matches(entries, names).items(): matches[name].extend(items)
        del entries
        blocks.update(item["sha256"] for item in record["inputs"])
    found = {name: items for name, items in matches.items() if items}
    # Exported files are counted separately. No implicit matching by output filename.
    inspections, lossless_files = [], {}
    for name in runs:
        for path in sorted((staging / name / "output").rglob("*.json")):
            if path.name == "manifest.json" and path.parent.parent.name == "lossless":
                from .lossless import validate_export
                verified = validate_export(path)
                lossless_files[verified["serialized_file_id"]] = verified["objects_verified"]
            elif path.name != "assets_map.json" and "lossless" not in path.relative_to(staging / name / "output").parts:
                result = inspect_native(path)
                inspections.append({k: v for k, v in result.items() if k != "raw"})
    return {"parser": PARSER_VERSION, "baseline_game_version": version,
            "baseline_reference_occurrences": len(refs), "unique_reference_names": len(names),
            "mapped_blocks": len(blocks), "mapped_asset_entries": asset_count,
            "located_unique_names": len(found),
            "located_reference_occurrences": sum(ref.get("name") in found for ref in refs),
            "target_resources_exported": 0, "target_control_structures_parsed": 0,
            "target_ir_converted": 0, "target_runtime_verified": 0,
            "missions_unblocked": 0, "matches": matches, "runs": runs, "rejected_runs": rejected,
            "lossless_unique_serialized_files": len(lossless_files), "lossless_objects_verified": sum(lossless_files.values()),
            "exported_json_inspections": inspections,
            "limitations": ["Cached maps require current-installation inventory/hash verification before claiming complete coverage.",
                            "Version equality is necessary, not proof of identical game build.",
                            "Export filenames do not prove object identity; duplicates may be skipped.",
                            "Base-only MonoBehaviour JSON is not recovered script data.",
                            "No native execution semantics have been verified."]}


class AnimeStudio:
    def __init__(self, executable: Path, game: Path, staging: Path, game_version: str):
        self.executable, self.game, self.staging = executable.resolve(), game.resolve(), staging.resolve()
        if not self.executable.is_file(): raise ValueError("AnimeStudio CLI not found")
        if not (self.game / "StarRail.exe").is_file(): raise ValueError("StarRail.exe not found")
        if self.staging.is_relative_to(self.game) or self.game.is_relative_to(self.staging):
            raise ValueError("Staging and game directories must be separate")
        cfg = configparser.ConfigParser()
        cfg.read(self.game / "config.ini", encoding="utf-8-sig")
        actual = {cfg.get(s, "game_version") for s in cfg.sections() if cfg.has_option(s, "game_version")}
        if actual != {game_version} or game_version == "unknown":
            raise ValueError("Game version is missing or differs from requested source version")
        self.version = game_version
        self.staging.mkdir(parents=True, exist_ok=True)

    def run(self, inputs: list[Path], name: str, *, export: str | None = None,
            containers: list[str] | None = None, timeout: int = 300, lossless: bool = False) -> dict:
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in name):
            raise ValueError("Invalid run name")
        if export not in {None, "Raw", "Dump", "Convert"}: raise ValueError("Unknown export mode")
        run = self.staging / name
        run.mkdir(exist_ok=False)
        copied, provenance = run / "input", []
        copied.mkdir(); (run / "output").mkdir()
        seen = set()
        for source in inputs:
            source = source.resolve()
            if not source.is_relative_to(self.game) or source.suffix != ".block" or not source.is_file():
                raise ValueError("Only installed game .block files may be staged")
            if source.name in seen: raise ValueError("Duplicate input basename")
            seen.add(source.name)
            target = copied / source.name
            shutil.copyfile(source, target)
            provenance.append({"original": source.relative_to(self.game).as_posix(),
                               "staged": str(target), "sha256": file_hash(target), "bytes": target.stat().st_size})
        if not provenance: raise ValueError("No input blocks")
        args = [str(self.executable), str(copied), str(run / "output"), "--game", "SR",
                "--types", *ASSET_TYPES]
        if export:
            args += ["--export_type", export, "--group_assets", "ByContainer"]
        else:
            args += ["--map_op", "AssetMap", "--map_type", "JSON"]
        if containers: args += ["--containers", *containers]
        record = {"parser": PARSER_VERSION, "game_version": self.version,
                  "tool_sha256": file_hash(self.executable), "inputs": provenance,
                  "command": args, "lossless": lossless, "started_at": datetime.now(timezone.utc).isoformat()}
        record["tool_assemblies"] = {name: file_hash(self.executable.parent / "bin" / name)
                                     for name in ("AnimeStudio.CLI.dll", "AnimeStudio.dll")
                                     if (self.executable.parent / "bin" / name).is_file()}
        if (self.game / "pkg_version").is_file():
            record["game_manifest_sha256"] = file_hash(self.game / "pkg_version")
        write_json(run / "run.json", record)
        with (run / "tool.log").open("wb") as log:
            try:
                env = os.environ.copy()
                env.pop("ASTRALOGUE_LOSSLESS", None)
                if lossless:
                    if not (self.executable.parent / "extension-build.json").is_file():
                        raise ValueError("Lossless extension build metadata missing")
                    env["ASTRALOGUE_LOSSLESS"] = "1"
                proc = subprocess.run(args, cwd=run, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=timeout, check=False, env=env)
                record["returncode"] = proc.returncode
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
        # CLI may exit 0 after catching a loader error. Output, not exit code, is evidence.
        files = [p for p in (run / "output").rglob("*") if p.is_file()]
        record["outputs"] = [{"path": p.relative_to(run).as_posix(), "bytes": p.stat().st_size,
                              "sha256": file_hash(p)} for p in sorted(files)]
        if lossless:
            from .lossless import validate_export
            manifests = list((run / "output/lossless").glob("*/manifest.json"))
            record["lossless_objects_verified"] = sum(validate_export(p)["objects_verified"] for p in manifests)
            record["lossless_serialized_files"] = len(manifests)
            if not manifests: raise ValueError("No lossless manifests; export did not succeed")
        if not export and (run / "output/assets_map.json").is_file():
            entries = load_map(run / "output/assets_map.json")
            record["asset_count"] = len(entries)
            record["types"] = dict(Counter(e["Type"] for e in entries))
        write_json(run / "run.json", record)
        return record


def inspect_native(path: Path) -> dict:
    """Lossless structured-object inventory. Never invent execution from clip order.

    Object/track fields are evidence only until their script semantics are known.
    Null exports from MonoBehaviour.ToType are not successful deserialization.
    """
    if path.suffix.lower() not in {".json", ".dat", ".txt", ".bytes"}:
        raise ValueError("Not a supported native asset export")
    result: dict = {"path": str(path), "sha256": file_hash(path), "structured": False,
                    "ir_converted": False, "runtime_verified": False, "references": [], "fields": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError):
        result["diagnostic"] = "Binary/TypeTree dump requires a supported decoder"
        return result
    if not isinstance(obj, (dict, list)):
        result["diagnostic"] = "No structured object (including null TypeTree export)"
        return result
    result["structured"] = True
    result["raw"] = obj
    from .native_timeline import BASE_FIELDS
    result["base_fields_only"] = isinstance(obj, dict) and set(obj) <= BASE_FIELDS
    fields = Counter()
    def walk(value, pointer=""):
        if isinstance(value, dict):
            if "m_PathID" in value:
                result["references"].append({"pointer": pointer, "raw": value})
            for key, child in value.items():
                fields[key] += 1
                walk(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, child in enumerate(value): walk(child, pointer + "/" + str(i))
    walk(obj)
    result["fields"] = dict(fields)
    result["diagnostic"] = ("Only Unity base fields exported; custom serialized payload missing"
                            if result["base_fields_only"] else
                            "Structure recovered; script/control semantics not yet verified")
    return result
