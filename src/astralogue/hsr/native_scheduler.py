"""Native hierarchy/scheduling audit and fail-closed compilation to generic IR."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from astralogue import __version__
from astralogue.compiler.schedule import ScheduledAction, compile_schedule
from astralogue.model import Bundle, Node, Edge, Mission, Diagnostic, load_json, file_hash
from .timeline_binary import decode


def control_relations(control: dict) -> dict:
    """Link only literal option signals to explicit WaitCustomString listeners."""
    listeners, options = {}, []
    for si, sequence in enumerate(control.get("OnStartSequece", [])):
        tasks = sequence.get("TaskList", [])
        if tasks and tasks[0].get("$type", "").split(".")[-1] == "WaitCustomString":
            value = tasks[0].get("CustomString")
            event = value.get("Value") if isinstance(value, dict) and set(value) == {"Value"} else None
            if isinstance(event, str):
                listeners.setdefault(event, []).append({"sequence": si,
                    "timeline_calls": [t["TimelineName"] for t in tasks if t.get("$type", "").split(".")[-1] == "PlayTimeline" and isinstance(t.get("TimelineName"), str)],
                    "raw_tasks": tasks})
        for ti, task in enumerate(tasks):
            if task.get("$type", "").split(".")[-1] != "PlayOptionTalk": continue
            for oi, option in enumerate(task.get("OptionList", [])):
                event = option.get("TriggerCustomString")
                options.append({"pointer": f"/OnStartSequece/{si}/TaskList/{ti}/OptionList/{oi}",
                                "sentence_id": option.get("TalkSentenceID"), "literal_event": event,
                                "raw": option})
    routes = []
    for option in options:
        event = option["literal_event"]
        candidates = listeners.get(event, []) if isinstance(event, str) else []
        routes.append({**option, "listeners": candidates,
                       "unique_listener": len(candidates) == 1,
                       "scope": "external control-script route, not native marker resume binding"})
    return {"option_routes": routes, "listeners": listeners}


def analyze(manifest: Path, sentence_ids: set[int], control: dict) -> dict:
    report = decode(manifest, sentence_ids, track_profile="binding-v2")
    objects = {o["path_id"]: o for o in report["objects"]}
    roots = [o for o in objects.values() if o["class"] == "TimelineAsset"]
    if len(roots) != 1: raise ValueError("Timeline root not uniquely decoded")
    root = roots[0]
    options = set()
    def option_ids(value):
        if isinstance(value, dict):
            if value.get("$type", "").split(".")[-1] == "PlayOptionTalk":
                options.update(o["TalkSentenceID"] for o in value.get("OptionList", []) if "TalkSentenceID" in o)
            for child in value.values(): option_ids(child)
        elif isinstance(value, list):
            for child in value: option_ids(child)
    option_ids(control)
    hierarchy, actions, blockers, seen = [], [], [], set()
    def traverse(pointer: dict, parent: int):
        pid = pointer["m_PathID"]
        if not pid: return
        if pointer["m_FileID"] != 0 or pid not in objects:
            blockers.append({"code": "unresolved_track", "reference": pointer}); return
        track = objects[pid]
        if pid in seen:
            blockers.append({"code": "shared_or_cyclic_track", "track": pid}); return
        seen.add(pid)
        if track.get("parent") != {"m_FileID": 0, "m_PathID": parent}:
            blockers.append({"code": "track_parent_mismatch", "track": pid}); return
        hierarchy.append({"parent": parent, "track": pid, "class": track["class"],
                          "binding_name": track.get("binding_name"), "binding_transform_path": track.get("binding_transform_path"),
                          "layout_status": track["layout_status"]})
        if track.get("parsing_error"):
            blockers.append({"code": "track_layout_unknown", "track": pid, "reason": track["parsing_error"]})
        for c in track.get("clips", []):
            asset = objects.get(c["asset"]["m_PathID"]) if c["asset"]["m_FileID"] == 0 else None
            action = {"track": pid, "clip": c, "object": asset, "handler_supported": False, "activation_verified": False}
            if asset and "talk_sentence_id" in asset:
                action.update(role="DIRECT_DIALOGUE", handler_supported=True)
            elif asset and asset["class"] == "SimpleTalkMarkerClip":
                sid = asset.get("marker_sentence_candidate")
                action.update(role="SEMANTICS_UNKNOWN", evidence={"words": asset.get("marker_words"),
                    "matches_option_text": sid in options if sid else False,
                    "warning": "Matching option ID does not establish marker action or resume condition"})
            elif asset and asset["class"] == "PauseMarkerClip":
                action.update(role="SEMANTICS_UNKNOWN", evidence={"payload_bytes": 0, "resume_binding": None})
            else: action["role"] = "SEMANTICS_UNKNOWN"
            actions.append(action)
        for child in track.get("children", []): traverse(child, pid)
    for pointer in root["tracks"]: traverse(pointer, root["path_id"])
    traverse(root["marker_track"], root["path_id"])
    boundary_pairs = []
    for action in actions:
        if not action["object"] or action["object"]["class"] != "PauseMarkerClip": continue
        candidates = [a for a in actions if a["track"] == action["track"] and a["handler_supported"]
                      and abs(a["clip"]["start"] + a["clip"]["duration"] - action["clip"]["start"]) < 1e-6]
        boundary_pairs.append({"pause_object": action["object"]["path_id"], "time": action["clip"]["start"],
                               "preceding_dialogue_candidates": [a["object"]["talk_sentence_id"] for a in candidates],
                               "resume_condition_verified": False})
    # Serialized flags without verified semantics must not be treated as defaults.
    blockers.append({"code": "unverified_track_activation", "reason": "Track prefix/activation flags have no verified field semantics"})
    blockers.extend({"code": "unverified_clip_behavior", "track": a["track"],
                     "path_id": a["clip"]["asset"]["m_PathID"], "time": a["clip"]["start"],
                     "class": a["object"]["class"] if a["object"] else None,
                     "evidence": a.get("evidence", {})} for a in actions if not a["handler_supported"])
    end_time = max((a["clip"]["start"] + a["clip"]["duration"] for a in actions), default=0)
    categories = {"DIRECT_DIALOGUE": sum(a["role"] == "DIRECT_DIALOGUE" for a in actions),
                  "VERIFIED_CONTROL": 0, "VERIFIED_MISSION_STATE": 0,
                  "VERIFIED_ACTOR_OR_PROP_STATE": 0, "PROVEN_VISUAL_ONLY": 0,
                  "SEMANTICS_UNKNOWN": sum(a["role"] == "SEMANTICS_UNKNOWN" for a in actions)}
    dependencies = [{"path_id": o["path_id"], "class": o["class"], "binding_name": o.get("binding_name"),
                     "binding_transform_path": o.get("binding_transform_path"),
                     "parent": o.get("parent"), "children": o.get("children", []),
                     "structural_role": "TRACK_HIERARCHY" if o["class"] == "GroupTrack" else "BOUND_OBJECT_REFERENCE",
                     "execution_category": "SEMANTICS_UNKNOWN", "layout_status": o["layout_status"],
                     "excluded_as_visual": False} for o in objects.values() if o["class"] and o["class"].endswith("Track")]
    report.update(root=root, hierarchy=hierarchy, scheduled_actions=actions, blockers=blockers,
                  end_time_lower_bound=end_time, end_policy_verified=False, categories=categories,
                  dependencies=dependencies, pure_visual_exemptions=[], full_timeline_verified=False)
    report["pause_boundary_evidence"] = boundary_pairs
    return report


def build(directory: Path, source: Path, control_path: Path) -> tuple[dict, Bundle]:
    source_meta = load_json(source / "source.json")
    rows = load_json(source / "ExcelOutput/TalkSentenceConfig.json")
    sentences = {row["TalkSentenceID"]: row for row in rows if "TalkSentenceID" in row}
    textmap = load_json(source / "TextMap/TextMapCHS.json")
    control = load_json(control_path)
    bundle = Bundle(metadata={"version": __version__, "source": source_meta,
                               "parser_version": "native-schedule-audit-v1", "scope": "complete Timeline call attempts",
                               "required_capabilities": ["call-return-v1"],
                               "inputs": {"TalkSentenceConfig": file_hash(source / "ExcelOutput/TalkSentenceConfig.json"),
                                          "TextMapCHS": file_hash(source / "TextMap/TextMapCHS.json"),
                                          "control": file_hash(control_path)}})
    bundle.text("default-title", "原生 Timeline 调度核验（未验证控制将阻塞）")
    relations = control_relations(control)
    bundle.metadata["native_control_relations"] = relations
    results = []
    for manifest in sorted(directory.glob("*/manifest.json")):
        run = load_json(manifest.parents[3] / "run.json")
        if run.get("game_version") != source_meta.get("game_version") or run.get("game_version") != "4.6.0":
            raise ValueError("Native schedule source version mismatch")
        report = analyze(manifest, set(sentences), control)
        native = load_json(manifest)
        root_id = report["root"]["path_id"]
        containers = [c for o in native["objects"] if o.get("asset_bundle") for c in o["asset_bundle"]["containers"]
                      if c["asset"] == {"m_FileID": 0, "m_PathID": root_id}]
        calls = []
        for si, seq in enumerate(control.get("OnStartSequece", [])):
            for ti, task in enumerate(seq.get("TaskList", [])):
                logical = task.get("TimelineName")
                if task.get("$type", "").split(".")[-1] == "PlayTimeline" and isinstance(logical, str):
                    if any(c["name"].casefold().endswith("/"+logical.casefold()) for c in containers):
                        calls.append({"pointer": f"/OnStartSequece/{si}/TaskList/{ti}", "raw": task})
        if len(calls) != 1: raise ValueError("Control script does not uniquely call the exported Timeline")
        mid = "hsr:native-schedule:"+report["serialized_file_id"]
        title = bundle.text(mid+":title", report["root"]["name"]+" · 完整 Timeline 调用核验")
        call, continuation = mid+":caller", mid+":after"
        bundle.missions.append(Mission(mid, title, call))
        actions = []
        for i, action in enumerate(report["scheduled_actions"]):
            obj = action["object"]
            if action["handler_supported"]:
                row = sentences[obj["talk_sentence_id"]]
                text = bundle.text("hsr:text:"+str(row["TalkSentenceText"]["Hash"]), textmap[str(row["TalkSentenceText"]["Hash"])])
                speaker = None
                if "TextmapTalkSentenceName" in row:
                    key = str(row["TextmapTalkSentenceName"]["Hash"])
                    if key in textmap: speaker = bundle.text("hsr:speaker:"+key, textmap[key])
                actions.append(ScheduledAction(str(i), action["clip"]["start"], "dialogue",
                    {"talk_sentence_id": obj["talk_sentence_id"], "native_duration": action["clip"]["duration"]}, text, speaker))
            else: actions.append(ScheduledAction(str(i), action["clip"]["start"], "UnverifiedNativeClip", action.get("evidence", {})))
        entry, returned = compile_schedule(bundle, mid, mid+":timeline", actions,
            report["end_time_lower_bound"], end_verified=report["end_policy_verified"], blockers=report["blockers"])
        bundle.metadata.setdefault("native_timeline_entries", {})[calls[0]["raw"]["TimelineName"]] = {
            "entry": entry, "returns": [returned] if returned else [], "mission": mid,
            "schedule_status": "BLOCKED" if report["blockers"] or not report["end_policy_verified"] else "STATICALLY_COMPILED"}
        bundle.nodes.extend([Node(call, mid, "call"), Node(continuation, mid, "unknown", data={"operation": "UncompiledCallerContinuation"})])
        bundle.edges.extend([Edge(call+":invoke", call, entry, "call"), Edge(call+":continuation", call, continuation)])
        if returned: bundle.edges.append(Edge(returned+":resume", returned, continuation, "return"))
        bundle.source_refs.append({"node": call, "file": str(control_path), "pointer": calls[0]["pointer"],
                                   "record": calls[0]["raw"], "sha256": file_hash(control_path), "container": containers})
        bundle.source_refs.append({"node": entry, "file": str(manifest), "record": report})
        bundle.metadata.setdefault("native_evidence", {})[report["serialized_file_id"]] = {
            "manifest": native, "serialized_file_hex": (manifest.parent / "serialized-file.dat").read_bytes().hex(),
            "export_provenance": {k: run.get(k) for k in ("tool_sha256", "tool_assemblies", "game_version", "game_manifest_sha256", "inputs")}}
        if report["blockers"] or not report["end_policy_verified"]:
            bundle.diagnostics.append(Diagnostic("native_schedule_unverified", "原生调度所需行为未证明，禁止跳过 Marker 或并行轨道", "error", mid, call))
        results.append(report)
    return {"timelines": len(results), "full_runtime_complete": 0,
            "control_relations": relations,
            "structural_parse_errors": dict(Counter(e["class"] for r in results for e in r["errors"])),
            "reports": results}, bundle
