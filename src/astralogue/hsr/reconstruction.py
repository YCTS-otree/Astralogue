"""HSR evidence adapter for an explicitly user-authorized text projection."""
from pathlib import Path

from astralogue import __version__
from astralogue.model import Bundle, Diagnostic, Mission, Node, file_hash, load_json
from astralogue.narrative import Reconstruction
from .native_scheduler import build as build_native, control_relations


def reconstruct(directory: Path, source: Path, control_path: Path) -> tuple[dict, Bundle]:
    report, strict = build_native(directory, source, control_path)
    control = load_json(control_path)
    control_hash = file_hash(control_path)
    prefix = "narrative:" + control_path.stem
    strict_id, reader_id = prefix + ":strict", prefix + ":reader"
    strict.text(strict_id + ":title", control_path.stem + " · Strict 控制入口（阻塞）")
    strict.missions.append(Mission(strict_id, strict_id + ":title", strict_id + ":entry"))
    strict.nodes.append(Node(strict_id + ":entry", strict_id, "unknown", data={"operation": "UnverifiedPerformanceInitialization", "raw": control}))
    strict.diagnostics.append(Diagnostic("unverified_performance", "轨道激活、暂停和结束契约未知", "error", strict_id, strict_id + ":entry"))
    r = Reconstruction(strict, reader_id, control_path.stem + " · Reader 文字阅读段", reader_id + ":entry")
    b = r.bundle
    b.metadata.update(version=__version__)
    info = r.info
    info["modes"][strict_id] = {"mode": "strict", "scope": "control_script"}
    info["entries"] = {"strict": strict_id, "reader": reader_id}
    info["game_version"] = strict.metadata["source"]["game_version"]
    info["game"] = "HSR"
    info["source_hashes"] = {**strict.metadata["inputs"], "control": control_hash}
    info["raw_control"] = control
    info["policy_description"] = "用户选择文字轨道，以原生静态时间字段阅读；不模拟激活、并行演出、暂停恢复或游戏任务完成"
    rows = load_json(source / "ExcelOutput/TalkSentenceConfig.json")
    sentences = {row["TalkSentenceID"]: row for row in rows if "TalkSentenceID" in row}
    textmap = load_json(source / "TextMap/TextMapCHS.json")

    def sentence(sid):
        row = sentences[sid]
        text = b.text("hsr:text:" + str(row["TalkSentenceText"]["Hash"]), textmap[str(row["TalkSentenceText"]["Hash"])])
        name = row.get("TextmapTalkSentenceName", {}).get("Hash")
        speaker = b.text("hsr:speaker:" + str(name), textmap[str(name)]) if str(name) in textmap else None
        return text, speaker

    seqs = control.get("OnStartSequece", [])
    relations = control_relations(control)
    listeners = relations["listeners"]
    def sid(si, ti): return reader_id + f":s{si}:t{ti}"
    entries = []
    timeline_by_ref = {}
    for manifest in directory.glob("*/manifest.json"):
        key = file_hash(manifest.parent / "serialized-file.dat")
        info["source_hashes"]["serialized_file:" + key] = key
        info["source_hashes"]["manifest:" + key] = file_hash(manifest)
    for ref, binding in strict.metadata["native_timeline_entries"].items():
        matches = [x for x in report["reports"] if binding["mission"] == "hsr:native-schedule:" + x["serialized_file_id"]]
        if len(matches) != 1: raise ValueError("Timeline evidence identity mismatch")
        timeline_by_ref[ref] = matches[0]

    def unknown(nid, operation, raw):
        r.node(nid, "unknown", operation=operation, raw=raw)

    def route(event):
        candidates = listeners.get(event, [])
        return sid(candidates[0]["sequence"], 0) if len(candidates) == 1 else None

    def timeline(nid, ref, target):
        native = timeline_by_ref.get(ref)
        if native is None:
            unknown(nid, "MissingExactTimeline", {"reference": ref}); return
        evidence = {"serialized_file": native["serialized_file_id"], "root": native["root"]["path_id"], "reference": ref}
        tracks = {a["track"] for a in native["scheduled_actions"] if a["role"] == "DIRECT_DIALOGUE"}
        if not tracks:
            unknown(nid, "NoVerifiedDialogueTrack", evidence); return
        r.node(nid, "choice", reader_action="track_selection", reader_message="轨道激活未知；请主动选择文字投影，不执行其他未知轨道")
        info["policies"][nid] = {"action": "track_selection", "official": False, "evidence": evidence,
            "unselected_track_policy": "outside selected reading scope; not proven visual-only"}
        for track in sorted(tracks):  # menu identity only; never an execution ordering
            stem = nid + ":track:" + str(track)
            end = stem + ":return"
            r.confirm(end, target, "所选文字轨道读毕；原生结束契约未知，确认返回控制脚本（不代表完整 Timeline 完成）", evidence, "timeline_return")
            actions = [a for a in native["scheduled_actions"] if a["track"] == track]
            groups = {}
            for clip_index, a in enumerate(actions): groups.setdefault(a["clip"]["start"], []).append((clip_index, a))
            following = end
            for time in sorted(groups, reverse=True):
                group = groups[time]
                fragments = []
                for clip_index, a in group:
                    obj = a["object"]
                    # One asset may be referenced by multiple Clip instances.
                    # The serialized slot distinguishes identity, never flow.
                    identity = str(a["clip"]["asset"]["m_PathID"]) + ":clip:" + str(clip_index)
                    entry, exit_ = stem + ":object:" + identity, stem + ":object:" + identity + ":after"
                    ev = {**evidence, "track": track, "clip_index": clip_index, "clip": a["clip"], "object": obj}
                    if a["role"] == "DIRECT_DIALOGUE":
                        text, speaker = sentence(obj["talk_sentence_id"])
                        b.nodes.append(Node(entry, reader_id, "dialogue", text, speaker,
                                            {"talk_sentence_id": obj["talk_sentence_id"], "native_evidence": ev}))
                        r.edge(entry, exit_, "native_structure", ev, policy="static_time_reading")
                    elif obj and obj["class"] in {"PauseMarkerClip", "SimpleTalkMarkerClip"}:
                        r.confirm(entry, exit_, f"{obj['class']} 恢复/触发语义未知，确认按文字投影继续", ev, "unknown_marker")
                    else:
                        unknown(entry, "UnknownNarrativeClip", ev)
                    r.node(exit_, "noop")
                    b.source_refs.append({"node": entry, "file": ref, "record": ev})
                    fragments.append((entry, exit_, str(obj["talk_sentence_id"]) if a["role"] == "DIRECT_DIALOGUE" else identity))
                if len(fragments) == 1:
                    r.edge(fragments[0][1], following, "native_structure", {**evidence, "time": time}, "static_time_reading")
                    following = fragments[0][0]
                else:
                    following = r.unordered(stem + ":time:" + str(time), fragments, following)
            label = b.text(stem + ":label", f"选择文字轨道 {track}：按静态时间阅读；其他轨道、激活和恢复机制未知，均不模拟")
            r.edge(nid, following, "native_structure", evidence, "track_selection", kind="option", text=label, value=str(track))

    for si, seq in enumerate(seqs):
        tasks = seq.get("TaskList", [])
        if not tasks: continue
        first_type = tasks[0].get("$type", "").split(".")[-1]
        if first_type == "WaitPerformanceEnd":
            info.setdefault("unprojected_sequences", []).append({"sequence": si, "raw": seq, "reason": "native completion listener outside selected reading scope"})
            continue
        if first_type not in {"WaitCustomString", "WaitPerformanceEnd"}: entries.append(sid(si, 0))
        for ti, task in enumerate(tasks):
            nid = sid(si, ti)
            target = sid(si, ti + 1) if ti + 1 < len(tasks) else None
            op = task.get("$type", "").split(".")[-1]
            ev = {"file": control_path.name, "sha256": control_hash, "pointer": f"/OnStartSequece/{si}/TaskList/{ti}", "raw": task}
            b.source_refs.append({"node": nid, **ev})
            if op == "PlayTimeline" and target:
                timeline(nid, task.get("TimelineName"), target)
            elif op in {"LevelPerformanceInitialize", "WaitSecond"} and target:
                r.confirm(nid, target, f"{op}：依据 TaskList 明确后继抽象为确认；不模拟世界/演出状态", ev, "nontext_confirmation")
            elif op == "WaitCustomString" and ti == 0 and target:
                r.node(nid, "wait", event=task["CustomString"]["Value"], consume=True)
                r.edge(nid, target, "original_control", ev)
            elif op == "TriggerCustomString" and target is None and route(task["CustomString"]["Value"]):
                event = task["CustomString"]["Value"]
                r.node(nid, "emit", event=event)
                r.edge(nid, route(event), "original_control", ev)
            elif op == "PlayOptionTalk" and target is None:
                options = task.get("OptionList", [])
                if not options or any(not route(o.get("TriggerCustomString")) for o in options):
                    unknown(nid, "AmbiguousOptionListener", ev); continue
                r.node(nid, "choice", option_events={str(o["TalkSentenceID"]): o["TriggerCustomString"] for o in options})
                for o in options:
                    text, _ = sentence(o["TalkSentenceID"])
                    r.edge(nid, route(o["TriggerCustomString"]), "original_control", {**ev, "option": o},
                           kind="option", text=text, value=str(o["TalkSentenceID"]))
            elif op == "EndPerformance" and target is None:
                end = nid + ":reading_end"
                r.node(end, "end", completion_scope="reader_selected_text_segment", original_game_completion=False)
                r.confirm(nid, end, "控制脚本已请求 EndPerformance；确认结束文字阅读段（未证明游戏任务或原生调度完成）", ev, "reading_end")
            else:
                unknown(nid, op or "UnknownTask", ev)
    if len(entries) == 1:
        r.confirm(reader_id + ":entry", entries[0], "启用 Reader：仅按已知脚本分支阅读所选文字轨道；未知行为需确认，非原游戏完整执行", {"control_sha256": control_hash}, "reader_consent")
    else:
        r.guide(reader_id + ":entry", {e: "候选控制入口 " + e for e in entries}, {"reason": "multiple independent sequences"})
    # Listener that waits for the native game's completion remains raw/unknown,
    # never promoted to a game-completion event by this reading projection.
    info["scope_exclusions"] = ["unselected tracks", "world state", "WaitPerformanceEnd/FinishLevelGraph game completion"]
    report = {"scope": control_path.stem, "strict_full_timelines": 0, "reader_full_game_timelines": 0,
              "reader_mission": reader_id, "strict_mission": strict_id, "native_resources": len(timeline_by_ref),
              "dialogue_carriers": sum(a["role"] == "DIRECT_DIALOGUE" for x in report["reports"] for a in x["scheduled_actions"]),
              "original_option_routes": relations["option_routes"], "community_patches": 0,
              "strict_complete_named_missions": 0, "reader_complete_named_missions": 0}
    return report, b
