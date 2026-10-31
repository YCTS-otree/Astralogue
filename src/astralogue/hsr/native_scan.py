"""Checkpointed build-only block scanning and exact target lookup."""
from __future__ import annotations

import configparser
import json
from pathlib import Path, PurePosixPath
import time
import uuid
import sqlite3

from astralogue.model import digest, file_hash, load_json
from .animestudio import AnimeStudio, write_json, normalize_resource
from .native_index import NativeIndex


def discover_blocks(game: Path) -> list[Path]:
    paths = []
    for relative in ("StreamingAssets/Asb/Windows", "Persistent/Asb/Windows"):
        paths.extend((game / "StarRail_Data" / relative).glob("*.block"))
    names = {}
    for path in sorted(paths):
        if path.name in names and file_hash(path) != file_hash(names[path.name]):
            raise ValueError("Different source blocks share a basename; explicit source priority required")
        names[path.name] = path
    return list(names.values())


def scope_manifest(game: Path, paths: list[Path]) -> str:
    return digest({"pkg_version": file_hash(game / "pkg_version"),
                   "blocks": [(p.relative_to(game).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]})


def inventory(game: Path, index: NativeIndex) -> dict:
    paths = discover_blocks(game)
    known = {r[0] for r in index.db.execute("SELECT DISTINCT name FROM blocks")}
    return {"total_blocks": len(paths), "indexed_names": sum(p.name in known for p in paths),
            "remaining_names": sum(p.name not in known for p in paths),
            "total_bytes": sum(p.stat().st_size for p in paths),
            "note": "Name inventory; scanner separately verifies current content hashes"}


def scan(game: Path, executable: Path, staging: Path, database: Path, game_version: str,
         max_batches: int = 256, batch_mib: int = 512, retry_failed: bool = False) -> dict:
    index = NativeIndex(database)
    try:
        index.ingest(staging)
        index.db.execute("""CREATE TABLE IF NOT EXISTS scan_jobs(
            manifest TEXT, name TEXT, state TEXT, sha TEXT, updated REAL, run TEXT, reason TEXT,
            PRIMARY KEY(manifest,name))""")
        pkg_hash = file_hash(game / "pkg_version")
        paths = discover_blocks(game)
        manifest = scope_manifest(game, paths)
        pending = {p.name for p in index.remaining(paths)}
        with index.db:
            for p in paths:
                cached = index.db.execute("SELECT sha256 FROM blocks WHERE name=? AND bytes=?", (p.name, p.stat().st_size)).fetchall()
                if p.name not in pending:
                    sha = cached[0][0] if len({r[0] for r in cached}) == 1 else file_hash(p)
                    index.db.execute("INSERT OR REPLACE INTO scan_jobs VALUES(?,?,?,?,?,?,?)",
                                     (manifest, p.name, "MAPPED", sha, time.time(), "cached", None))
                else:
                    index.db.execute("INSERT OR IGNORE INTO scan_jobs VALUES(?,?,?,?,?,?,?)",
                                     (manifest, p.name, "PENDING", None, time.time(), None, None))
                    index.db.execute("UPDATE scan_jobs SET state='PENDING',updated=?,reason='content changed' WHERE manifest=? AND name=? AND state='MAPPED'",
                                     (time.time(), manifest, p.name))
            index.db.execute("UPDATE scan_jobs SET state='PENDING' WHERE manifest=? AND state='RUNNING' AND updated<?", (manifest, time.time()-900))
            if retry_failed: index.db.execute("UPDATE scan_jobs SET state='PENDING' WHERE manifest=? AND state='FAILED'", (manifest,))
        def progress():
            states = dict(index.db.execute("SELECT state,count(*) FROM scan_jobs WHERE manifest=? GROUP BY state", (manifest,)))
            value = {"scan_namespace": manifest, "manifest_sha256": pkg_hash, "total_blocks": len(paths),
                     "states": states, "full_map_complete": states.get("MAPPED", 0) == len(paths)}
            write_json(staging / "m59-scan-progress.json", value)
            return value
        progress()
        lookup = {p.name: p for p in paths}
        tool = AnimeStudio(executable, game, staging, game_version)
        for _ in range(max_batches):
            if file_hash(game / "pkg_version") != pkg_hash: raise ValueError("Installation manifest changed during scan")
            names = [r[0] for r in index.db.execute("SELECT name FROM scan_jobs WHERE manifest=? AND state='PENDING' ORDER BY name", (manifest,))]
            selected, total = [], 0
            for name in names:
                size = lookup[name].stat().st_size
                if size + total <= batch_mib * 1024**2:
                    selected.append(lookup[name]); total += size
                if len(selected) == 128: break
            if not selected: break
            run_name = "m59-scan-" + uuid.uuid4().hex[:12]
            with index.db:
                for p in selected: index.db.execute("UPDATE scan_jobs SET state='RUNNING',updated=?,run=? WHERE manifest=? AND name=?",
                                                    (time.time(), run_name, manifest, p.name))
            try:
                record = tool.run(selected, run_name, timeout=300)
                imported = index.ingest(staging)
                if run_name in imported["rejected_runs"] or record.get("timed_out") or "asset_count" not in record:
                    raise ValueError("Incomplete or diagnostic-bearing asset map; not cached as complete")
                with index.db:
                    for item in record["inputs"]:
                        index.db.execute("UPDATE scan_jobs SET state='MAPPED',sha=?,updated=?,reason=NULL WHERE manifest=? AND name=?",
                                         (item["sha256"], time.time(), manifest, Path(item["staged"]).name))
            except (OSError, ValueError) as ex:
                with index.db:
                    for p in selected: index.db.execute("UPDATE scan_jobs SET state='FAILED',updated=?,reason=? WHERE manifest=? AND name=?",
                                                        (time.time(), str(ex), manifest, p.name))
            value = progress(); value["last_run"] = run_name
            print(json.dumps(value), flush=True)
        return progress()
    finally: index.close()


def target_report(database: Path, baseline_ir: Path, cutscene_config: Path | None = None, *, game: Path | None = None) -> dict:
    index = NativeIndex(database)
    try:
        b = load_json(baseline_ir)
        refs = [r["name"] for m in b["metadata"]["hsr_metrics"].values() for r in m.get("timeline_references", [])]
        specs = {normalize_resource(name): name for name in refs}
        aliases, configured_rows = {}, {}
        if cutscene_config:
            source = load_json(cutscene_config.parent.parent / "source.json")
            expected = b["metadata"]["source"]
            if expected.get("revision") in {None, "unknown"} or source.get("revision") != expected.get("revision") or source.get("game_version") != expected.get("game_version"):
                raise ValueError("CutSceneConfig source version mismatch")
            rows = load_json(cutscene_config)
            for row in rows.values() if isinstance(rows, dict) else rows:
                name, path = row.get("CutSceneName"), row.get("CutScenePath")
                if name in refs and isinstance(path, str):
                    configured_rows[name] = row
                    normalized = normalize_resource(path)
                    if normalized in aliases and aliases[normalized] != name: raise ValueError("Cutscene path conflict")
                    aliases[normalized] = name
        short = {name for name in specs if "/" not in name}
        spec_id = digest({"refs": sorted(refs), "aliases": aliases})
        index.db.executescript("""CREATE TABLE IF NOT EXISTS target_progress(spec TEXT PRIMARY KEY,last_row INTEGER);
            CREATE TABLE IF NOT EXISTS target_matches(spec TEXT, reference TEXT, kind TEXT, block_sha TEXT, container TEXT,
            PRIMARY KEY(spec,reference,kind,block_sha,container));""")
        previous = index.db.execute("SELECT last_row FROM target_progress WHERE spec=?", (spec_id,)).fetchone()
        cursor = previous[0] if previous else 0
        found = set()
        # Separate read snapshot: never upgrade a long read transaction into a writer.
        reader = sqlite3.connect(database, timeout=30)
        try:
            upper = reader.execute("SELECT coalesce(max(rowid),0) FROM assets").fetchone()[0]
            for rowid, sha, container, raw in reader.execute("SELECT rowid,block_sha,container,record FROM assets WHERE rowid>? AND rowid<=? ORDER BY rowid", (cursor, upper)):
                try: normalized = normalize_resource(container)
                except ValueError: continue
                hits = []
                if normalized in specs: hits.append((specs[normalized], "EXACT_CONTAINER"))
                if normalized in aliases: hits.append((aliases[normalized], "CONFIGURED_CUTSCENE_PATH"))
                name = json.loads(raw)["Name"].casefold()
                for candidate in {name, PurePosixPath(normalized).stem} & short:
                    hits.append((specs[candidate], "EXACT_NAME_CANDIDATE"))
                for reference, kind in hits: found.add((spec_id, reference, kind, sha, container))
                cursor = rowid
        finally: reader.close()
        with index.db:
            index.db.executemany("INSERT OR IGNORE INTO target_matches VALUES(?,?,?,?,?)", sorted(found))
            index.db.execute("INSERT OR REPLACE INTO target_progress VALUES(?,?)", (spec_id, upper))
        matches = [{"reference": ref, "kind": kind, "block_sha256": sha, "container": container}
                   for ref, kind, sha, container in index.db.execute("SELECT reference,kind,block_sha,container FROM target_matches WHERE spec=? ORDER BY reference,container", (spec_id,))]
        if game:
            cfg = configparser.ConfigParser(); cfg.read(game / "config.ini", encoding="utf-8-sig")
            versions = {cfg.get(s, "game_version") for s in cfg.sections() if cfg.has_option(s, "game_version")}
            if versions != {b["metadata"]["source"].get("game_version")}: raise ValueError("Target report game version mismatch")
            paths = discover_blocks(game)
            scope = scope_manifest(game, paths)
            active = {r[0] for r in index.db.execute("SELECT sha FROM scan_jobs WHERE manifest=? AND state='MAPPED'", (scope,))}
            if not active: raise ValueError("No verified current-installation scan checkpoint")
            matches = [m for m in matches if m["block_sha256"] in active]
        exact = {r["reference"] for r in matches if r["kind"] in {"EXACT_CONTAINER", "CONFIGURED_CUTSCENE_PATH"}}
        candidates = {r["reference"] for r in matches}
        variant_paths = {}
        for name in set(refs)-candidates:
            row = configured_rows.get(name, {})
            path = row.get("CutScenePath", "")
            if row.get("IsPlayerInvolved") is True and path.endswith(".playable"):
                for suffix in ("_f", "_m"):
                    variant_paths["assets/asbres/" + normalize_resource(path[:-9] + suffix + ".playable")] = name
        variants = []
        if variant_paths:
            placeholders = ",".join("?" for _ in variant_paths)
            for sha, container in index.db.execute(f"SELECT DISTINCT block_sha,container FROM assets WHERE container COLLATE NOCASE IN ({placeholders})", list(variant_paths)):
                if game and sha not in active: continue
                variants.append({"reference": variant_paths[container.casefold()], "container": container,
                                 "block_sha256": sha, "kind": "UNVERIFIED_GENDER_SUFFIX", "resolved": False})
        return {"denominator_occurrences": len(refs), "denominator_unique": len(set(refs)),
                "exact_container_references": len(exact), "references_with_candidates": len(candidates),
                "matches": matches, "unlocated": sorted(set(refs)-candidates),
                "cutscene_aliases": aliases, "alias_config_sha256": file_hash(cutscene_config) if cutscene_config else None,
                "current_installation_checked": game is not None,
                "hash_validation_scope": "Hashes verified by last matching scan checkpoint; this report checks version/path/size/mtime metadata",
                "gender_suffix_candidates": variants,
                "assets_indexed": index.db.execute("SELECT count(*) FROM assets").fetchone()[0],
                "note": "Name candidates are not resolved Timeline controls; export and version validation still required"}
    finally: index.close()
