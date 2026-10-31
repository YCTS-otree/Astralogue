"""Trace native dialogue clips into explicitly scoped, blocked-continuation IR."""
from pathlib import Path

from astralogue import __version__
from astralogue.model import Bundle, Node, Edge, Mission, Diagnostic, load_json, file_hash
from .timeline_binary import decode


def recover(manifest: Path, source: Path, control: Path) -> tuple[dict, Bundle]:
    run = load_json(manifest.parents[3] / "run.json")
    version = load_json(source / "source.json")
    if version.get("game_version") != run.get("game_version") or run.get("game_version") != "4.6.0":
        raise ValueError("Native layout/source version mismatch")
    table = load_json(source / "ExcelOutput/TalkSentenceConfig.json")
    sentences = {int(row["TalkSentenceID"]): row for row in (table.values() if isinstance(table, dict) else table)
                 if "TalkSentenceID" in row}
    textmap = load_json(source / "TextMap/TextMapCHS.json")
    report = decode(manifest, set(sentences))
    objects = {o["path_id"]: o for o in report["objects"]}
    references = []
    def walk(value):
        if isinstance(value, dict):
            if value.get("$type", "").split(".")[-1] == "PlayTimeline" and isinstance(value.get("TimelineName"), str):
                references.append(value["TimelineName"])
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(load_json(control))
    native_manifest = load_json(manifest)
    container_paths = {c for o in native_manifest["objects"] for c in o["containers"] if c}
    matches = [ref for ref in references if any(c.casefold().endswith("/" + ref.casefold()) for c in container_paths)]
    if len(matches) != 1: raise ValueError("Control script does not uniquely reference this Timeline container")
    targets = {c["asset"]["m_PathID"] for o in native_manifest["objects"] if o.get("asset_bundle")
               for c in o["asset_bundle"]["containers"] if c["asset"]["m_FileID"] == 0
               and c["name"].casefold().endswith("/" + matches[0].casefold())}
    roots = [objects[pid] for pid in targets if pid in objects and objects[pid]["class"] == "TimelineAsset"]
    if len(roots) != 1: raise ValueError("Timeline root ambiguous")
    root = roots[0]
    container_evidence = [c for o in native_manifest["objects"] if o.get("asset_bundle")
                          for c in o["asset_bundle"]["containers"]
                          if c["asset"] == {"m_FileID": 0, "m_PathID": root["path_id"]}]
    routes = []
    def traverse(pid, ancestry):
        if pid not in objects or pid in ancestry: return
        track = objects[pid]
        path = ancestry + [pid]
        if track.get("class") == "PlaySimpleTalkTrack" and "clips" in track:
            for clip in track["clips"]:
                ptr = clip["asset"]
                if ptr["m_FileID"] != 0: continue
                obj = objects.get(ptr["m_PathID"], {})
                if "talk_sentence_id" in obj:
                    routes.append({"control": str(control), "control_sha256": file_hash(control),
                        "timeline_reference": matches[0], "serialized_file_id": report["serialized_file_id"],
                        "container_evidence": container_evidence,
                        "track_path": path, "clip": clip, "dialogue_object": obj})
        for ref in track.get("children", []):
            if ref["m_FileID"] == 0:
                target = objects.get(ref["m_PathID"], {})
                if not target: continue  # unsupported branch remains in decoder diagnostics
                if target.get("parent") != {"m_FileID": 0, "m_PathID": pid}:
                    raise ValueError("Track child/parent relationship mismatch")
                traverse(ref["m_PathID"], path)
    for ptr in root["tracks"]:
        if ptr["m_FileID"] == 0: traverse(ptr["m_PathID"], [root["path_id"]])
    report["dialogue_routes"] = routes
    report["scope"] = "verified dialogue clip fragments, not complete Timeline execution"
    b = Bundle(metadata={"parser_version": "native-dialogue-clip-v1", "version": __version__, "game": "hsr", "source": version,
                         "native_game_manifest": run.get("game_manifest_sha256"),
                         "native_control_scope": report["scope"], "languages": ["CHS"]})
    b.metadata["native_evidence"] = {report["serialized_file_id"]: {
        "manifest": native_manifest,
        "serialized_file_hex": (manifest.parent / "serialized-file.dat").read_bytes().hex(),
        "tool_sha256": run["tool_sha256"], "tool_assemblies": run.get("tool_assemblies", {}),
        "inputs": run["inputs"]}}
    b.text("default-title", "原生 Timeline 台词片段（后续控制未解析）")
    for route in routes:
        obj = route["dialogue_object"]; sid = obj["talk_sentence_id"]
        row = sentences[sid]
        text = textmap.get(str(row["TalkSentenceText"]["Hash"]))
        if not isinstance(text, str): raise ValueError(f"Missing original text for {sid}")
        mid = "hsr:native:" + report["serialized_file_id"] + ":" + str(obj["path_id"])
        title = mid + ":title"; line = mid + ":line"; blocked = mid + ":blocked"
        b.text(title, f"原生台词 {sid} · {route['clip']['start']:g}s（片段）")
        b.missions.append(Mission(mid, title, line, original_id=str(sid)))
        speaker = None
        if isinstance(row.get("TextmapTalkSentenceName"), dict):
            value = textmap.get(str(row["TextmapTalkSentenceName"].get("Hash")))
            if isinstance(value, str): speaker = b.text(mid+":speaker", value)
        key = b.text("hsr:text:" + str(row["TalkSentenceText"]["Hash"]), text)
        b.nodes.extend([Node(line, mid, "dialogue", key, speaker,
                             {"talk_sentence_id": sid, "native_start": route["clip"]["start"],
                              "native_duration": route["clip"]["duration"]}),
                        Node(blocked, mid, "unknown", data={"operation": "NativeTimelineContinuation",
                             "reason": "片段结束；暂停标记、并行轨道及后续状态尚未验证"})])
        b.edges.append(Edge(mid+":next", line, blocked))
        b.source_refs.append({"node": line, "file": str(manifest), "record": route})
        b.diagnostics.append(Diagnostic("native_fragment_only", "只验证此原生台词 Clip，不能证明整条 Timeline 可执行", "warning", mid))
    return report, b


def recover_many(directory: Path, source: Path, control: Path) -> tuple[dict, Bundle]:
    manifests = sorted(directory.glob("*/manifest.json"))
    if not manifests: raise ValueError("No lossless SerializedFile manifests")
    combined, reports = Bundle(), []
    combined.metadata["native_evidence"] = {}
    for manifest in manifests:
        report, bundle = recover(manifest, source, control)
        combined.chapters = bundle.chapters
        combined.metadata.update({k: v for k, v in bundle.metadata.items() if k != "native_evidence"})
        combined.metadata["native_evidence"].update(bundle.metadata["native_evidence"])
        combined.missions.extend(bundle.missions); combined.nodes.extend(bundle.nodes)
        combined.edges.extend(bundle.edges); combined.source_refs.extend(bundle.source_refs)
        combined.diagnostics.extend(bundle.diagnostics)
        for key, langs in bundle.texts.items():
            for lang, text in langs.items(): combined.text(key, text, lang)
        reports.append(report)
    return {"serialized_files": len(reports),
            "objects_verified": sum(r["validation"]["objects_verified"] for r in reports),
            "verified_dialogue_clips": sum(len(r["dialogue_routes"]) for r in reports),
            "full_timelines_runtime_complete": 0,
            "reports": reports}, combined
