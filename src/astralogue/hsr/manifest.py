"""Mission classification and evidence ledger; never invents execution order."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from astralogue.adapters.hsr import rows
from astralogue.model import file_hash, load_json

CATEGORIES = {"Main": "TRAILBLAZE", "Gap": "CONTINUANCE", "Companion": "COMPANION", "Branch": "ADVENTURE", "Daily": "DAILY"}
PARSER_VERSION = "hsr-mainline-1"


def table(root: Path, name: str, key: str) -> dict:
    p = root / "ExcelOutput" / (name + ".json")
    return rows(load_json(p), key) if p.exists() else {}


def create_manifest(root: Path, lang: str = "CHS") -> dict:
    main = table(root, "MainMission", "MainMissionID")
    if not main: raise ValueError("主线识别需要 MainMission.json，不能从文件名推断任务类型")
    maps = {}
    for p in [root / "TextMap" / f"TextMap{lang}.json", root / "TextMap" / f"TextMapMain{lang}.json"]:
        if p.exists(): maps.update(load_json(p))
    types = table(root, "MainMissionType", "Type")
    chapters = table(root, "MissionChapterConfig", "ID")
    source = load_json(root / "source.json") if (root / "source.json").exists() else {"revision": "unknown"}
    source = {k: v for k, v in source.items() if k not in {"files", "resource_index"}}
    index = load_json(root / "resource-index.json") if (root / "resource-index.json").exists() else {}
    if source.get("revision") not in {None, "unknown"} and index.get("revision") not in {None, source["revision"]}:
        raise ValueError("资源索引与任务数据来源版本冲突")
    catalog = index.get("files", {})
    by_folder = {}
    for path in catalog:
        parts = path.split("/")
        folder = None
        if parts[:3] == ["Config", "Level", "Mission"] and len(parts) > 4: folder = parts[3]
        elif parts[:2] == ["Story", "Mission"] and len(parts) > 3: folder = parts[2]
        elif parts[:3] == ["Story", "Discussion", "Mission"] and len(parts) > 4: folder = parts[3]
        if folder: by_folder.setdefault(folder, []).append(path)

    def text(obj):
        return maps.get(str(obj.get("Hash"))) if isinstance(obj, dict) else None

    missions = []
    for mid, record in sorted(main.items()):
        directory = root / "Config/Level/Mission" / mid
        ipath, ppath = directory / f"MissionInfo_{mid}.json", directory / f"MissionInfo_{mid}.partial.json"
        info, partial = load_json(ipath) if ipath.exists() else {}, load_json(ppath) if ppath.exists() else {}
        definitions = partial.get("SubMissionList", info.get("SubMissionList", []))
        errors = []
        if info.get("MainMissionID") is not None and str(info["MainMissionID"]) != mid: errors.append("MissionInfo.MainMissionID conflict")
        submissions = []
        for sub in definitions:
            if str(sub.get("MainMissionID", mid)) != mid:
                errors.append(f"SubMission {sub.get('ID')} ownership conflict"); continue
            path = sub.get("MissionJsonPath")
            submissions.append({"id": str(sub["ID"]), "resource": path, "local": bool(path and (root / path).is_file()),
                                "catalogued": path in catalog, "take_type": sub.get("TakeType"), "dependencies": sub.get("TakeParamIntList", []),
                                "finish_type": sub.get("FinishType"), "finish_key": sub.get("ParamStr1"), "raw": sub})
        candidates = by_folder.get(mid, [])
        category = CATEGORIES.get(record.get("Type"), "OTHER")
        chapter = chapters.get(str(record.get("ChapterID")), {})
        has_title = isinstance(record.get("Name"), dict) and "Hash" in record["Name"]
        story_candidate = has_title and info.get("IsShow") is not False and record.get("SubType") != "System"
        missions.append({"id": mid, "title": text(record.get("Name")), "category": category,
                         "classification": {"field": "MainMission.Type", "value": record.get("Type"), "label": text(types.get(str(record.get("Type")), {}).get("TypeName")), "inferred": False},
                         "subtype": record.get("SubType"), "chapter": record.get("ChapterID"), "chapter_title": text(chapter.get("ChapterName")), "world": record.get("WorldID"),
                         "named_story_candidate": story_candidate,
                         "visibility_evidence": {"has_title_hash": has_title, "explicit_is_show": info.get("IsShow"), "subtype": record.get("SubType")},
                         "display_priority": record.get("DisplayPriority"), "prerequisites": record.get("TakeParam", []), "prerequisite_operation": record.get("TakeOperation"),
                         "next_declared": record.get("NextMainMissionList", []), "next_track": record.get("NextTrackMainMission"),
                         "entries": [str(x) for x in info.get("StartSubMissionList", [])], "finish_submissions": [str(x) for x in info.get("FinishSubMissionList", [])],
                         "submissions": submissions, "candidate_resources": candidates, "candidate_association": "directory_only_not_execution_order",
                         "provenance": {"source": source, "main_table": "ExcelOutput/MainMission.json", "main_id": mid,
                                        "info": ipath.relative_to(root).as_posix(), "partial": ppath.relative_to(root).as_posix(),
                                        "info_sha256": file_hash(ipath) if ipath.is_file() else None,
                                        "partial_sha256": file_hash(ppath) if ppath.is_file() else None},
                         "parse_status": "CONFLICT" if errors else "INDEXED" if info else "MISSING_DEFINITION",
                         "completeness": "UNVERIFIED", "errors": errors, "raw": record})
    return {"manifest_version": 1, "parser_version": PARSER_VERSION, "language": lang, "source": source,
            "denominator": {"file": "ExcelOutput/MainMission.json", "sha256": file_hash(root / "ExcelOutput/MainMission.json"),
                            "rule": "explicit Type field; includes System/Endmost records, not inferred from IDs", "catalog_complete": index.get("complete", False),
                            "catalog_scope": index.get("scopes", ["Config/Level/Mission", "Story", "ExcelOutput", "TextMap"])},
            "acquisition": load_json(root / "acquisition.json") if (root / "acquisition.json").exists() else {"mode": "user-provided local directory"},
            "categories": dict(Counter(m["category"] for m in missions)), "missions": missions}
