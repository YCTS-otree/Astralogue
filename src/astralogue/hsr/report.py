"""Coverage with separate acquisition, text, graph and Runtime denominators."""
from collections import Counter

from astralogue.runtime import BlockedEvent, ChoiceEvent, DiagnosticEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack
from astralogue.validation.explore import explore


def coverage(pack: StoryPack, max_states: int = 1000, max_steps: int = 10000) -> dict:
    manifest = pack.metadata.get("mission_manifest")
    if not manifest: raise ValueError("此 StoryPack 没有 Mission Manifest")
    labels = pack.metadata.get("mission_labels", {})
    metrics = pack.metadata.get("hsr_metrics", {})
    definitions = [m for m in manifest["missions"] if m["category"] == "TRAILBLAZE"]
    mission_rows = {m["id"]: m for m in pack.missions(lang=manifest["language"])}
    summary = Counter()
    details, unsupported, missing, fragments, missing_text = [], Counter(), [], [], []
    dialogue_total = dialogue_resolved = timeline_total = timeline_resolved = option_total = option_edges = 0
    for definition in definitions:
        mid = "hsr:mission:" + definition["id"]
        metric = metrics.get(mid, {})
        controllers = [s for s in definition["submissions"] if s["resource"]]
        acquired = sum(s["local"] for s in controllers)
        summary["identified"] += 1
        story = definition.get("named_story_candidate", True)
        summary["named_story_candidates"] += story
        summary["definitions_available"] += definition["parse_status"] == "INDEXED"
        summary["some_controller_resources_available"] += acquired > 0
        summary["all_declared_controller_resources_available"] += bool(controllers) and acquired == len(controllers)
        summary["imported_control_resources"] += bool(metric.get("resources"))
        row = mission_rows.get(mid)
        if not row: continue
        summary[row["status"]] += 1
        rt = Runtime(pack, mid, manifest["language"])
        visible = False
        for _ in range(min(max_steps, 1000)):
            first = rt.next()
            if isinstance(first, DiagnosticEvent): continue
            visible = isinstance(first, (DialogueEvent, ChoiceEvent)); break
        summary["enterable_with_text_or_choice"] += visible and story
        explored = explore(pack, mid, manifest["language"], max_states, max_steps)
        complete = bool(explored["endings"]) and not explored["blocked"] and not explored["truncated"]
        summary["runtime_complete_all_main_records"] += complete
        summary["technical_records_runtime_complete"] += complete and not story
        summary["runtime_complete_known_initial_state"] += complete and story
        has_text = bool(explored["dialogue_nodes"])
        summary["runtime_complete_with_dialogue"] += complete and has_text and story
        all_known = complete and has_text and not metric.get("missing_resources") and not metric.get("unsupported") and acquired == len(controllers) and len(explored["choices_explored"]) == metric.get("option_edges", 0)
        summary["all_known_branches_complete"] += all_known and story
        summary["runtime_truncated"] += explored["truncated"]
        refs = metric.get("dialogue_references", [])
        # Imported texts are keyed by original hash; the resolved occurrence count
        # is computed at build time before the large upstream table is discarded.
        resolved = 0
        for sid, key in zip(refs, metric.get("dialogue_text_keys", [])):
            try: pack.text(key, manifest["language"]); resolved += 1
            except ValueError: missing_text.append({"mission": mid, "sentence_id": sid, "text_key": key})
        timelines = metric.get("timeline_references", [])
        dialogue_total += len(refs); dialogue_resolved += resolved
        timeline_total += len(timelines); timeline_resolved += sum(t["resolved"] for t in timelines)
        option_total += metric.get("option_references", 0); option_edges += metric.get("option_edges", 0)
        unsupported.update(metric.get("unsupported", {}))
        missing.extend({"mission": mid, **r} for r in metric.get("missing_resources", []))
        details.append({"id": definition["id"], "title": definition["title"], "static_status": row["status"],
                        "named_story_candidate": story,
                        "declared_controllers": len(controllers), "acquired_controllers": acquired,
                        "resources_parsed": len(metric.get("resources", [])), "enterable": visible,
                        "runtime_complete": complete, "has_executed_dialogue": has_text, "all_known_branches_complete": all_known,
                        "runtime": explored})
    for mid, label in labels.items():
        if label["scope"] not in {"PERFORMANCE_FRAGMENT", "SUBMISSION_FRAGMENT"}: continue
        result = explore(pack, mid, manifest["language"], max_states, max_steps)
        fragments.append({"id": mid, **label, "runtime": result,
                          "complete_fragment": bool(result["endings"]) and not result["blocked"] and not result["truncated"]})

    def ratio(resolved, total):
        return {"resolved": resolved, "total": total, "ratio": resolved / total if total else None}

    fragment_summary = {}
    for scope in ["PERFORMANCE_FRAGMENT", "SUBMISSION_FRAGMENT"]:
        group = [f for f in fragments if f["scope"] == scope]
        fragment_summary[scope] = {"total": len(group), "complete_known_initial_state": sum(f["complete_fragment"] for f in group),
                                  "complete_with_dialogue": sum(f["complete_fragment"] and bool(f["runtime"]["dialogue_nodes"]) for f in group)}
    return {"report_version": 1, "pack_id": pack.metadata["pack_id"], "source": manifest["source"], "fragment_summary": fragment_summary,
            "denominator": manifest["denominator"], "acquisition": manifest.get("acquisition"), "summary": dict(summary),
            "dialogue_references": ratio(dialogue_resolved, dialogue_total),
            "timeline_control_container_references": ratio(timeline_resolved, timeline_total),
            "option_target_references": ratio(option_edges, option_total),
            "unsupported_instructions": dict(unsupported.most_common()), "missing_resources": missing,
            "missing_dialogue_references": missing_text,
            "source_conflicts": pack.metadata.get("source_conflicts", []), "missions": details, "fragments": fragments,
            "limits": {"max_states_per_mission": max_states, "max_steps_per_mission": max_steps},
            "limitations": ["MainMission.Type=Main is the known denominator, not a claim about all game content.",
                            "Text denominators only cover explicit IDs in acquired control resources; missing Timeline text is not enumerable.",
                            "Timeline container resolution does not prove every contained opcode is supported.",
                            "Fragment completion never counts as main mission completion.",
                            "Runtime completion is scoped to the recorded initial state and bounded choices; external game-world states are not fabricated."]}
