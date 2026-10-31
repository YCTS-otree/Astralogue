"""Bounded real-data verification, separate from game-neutral Runtime.

Writes game text only to the requested, ignored data directory. Does not scan
or access any game installation, native exporter, or upstream resource files.
"""
import argparse
from collections import Counter
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from astralogue.model import load_json
from astralogue.narrative import audit
from astralogue.runtime import BlockedEvent, ChoiceEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def walk(pack, decisions, save):
    info = pack.metadata["narrative"]
    rt = Runtime(pack, info["entries"]["reader"])
    decisions = iter(decisions)
    lines, input_ = [], []
    for _ in range(300):
        e = rt.next()
        if isinstance(e, DialogueEvent):
            lines.append(pack.node(e.node).data["talk_sentence_id"]); input_.append("")
        elif isinstance(e, ChoiceEvent):
            action = pack.node(e.node).data.get("reader_action")
            if action:
                if len(e.options) != 1: raise ValueError("需要人工选择轨道/歧义顺序；自动验证禁止任选")
                value = e.options[0].value
            else: value = next(decisions)
            index = next(i for i, o in enumerate(e.options) if o.value == value)
            rt.choose(value); input_.append(str(index + 1))
        elif isinstance(e, EndEvent):
            rt.save(save)
            result = audit(pack, load_json(save))
            if not isinstance(Runtime.load(pack, save).next(), EndEvent): raise AssertionError("Restore mismatch")
            return {"dialogue_ids": lines, "audit": result}, "\n".join(input_ + ["", ""])
        else: raise AssertionError(f"Reading blocked: {e}")
    raise AssertionError("300 event bound exceeded")


def verify(path, decisions, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    runs, seen, policies, choices = [], set(), Counter(), set()
    with StoryPack(path) as pack:
        info = pack.metadata["narrative"]
        strict = Runtime(pack, info["entries"]["strict"]).next()
        if not isinstance(strict, BlockedEvent): raise AssertionError("Strict must preserve the unverified boundary")
        native_calls = [m["id"] for m in pack.missions() if m["id"].startswith("hsr:native-schedule:")]
        native_blocked = []
        for mission in native_calls:
            event = Runtime(pack, mission).next()
            if not isinstance(event, BlockedEvent): raise AssertionError("Unexpected Strict native completion")
            native_blocked.append({"mission": mission, "node": event.node, "code": event.code})
        for i, selection in enumerate(decisions):
            run, input_ = walk(pack, selection, directory / f"{name}-{i}.save.json")
            run["selection"] = selection; runs.append(run)
            seen.update(run["dialogue_ids"])
            for r in run["audit"]["records"]:
                if r["action"] == "original_choice": choices.add(r["value"])
                else: policies[r["action"]] += 1
            if i == 0:
                write(directory / f"{name}-audit.json", run["audit"])
                env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}
                for key in list(env):
                    if key.startswith("ASTRALOGUE_HSR_"): env.pop(key)
                with tempfile.TemporaryDirectory() as cwd:
                    result = subprocess.run([sys.executable, "-m", "astralogue", "reader", "play", "--pack", str(path.resolve()),
                        "--autosave", str((directory / f"{name}-cli.save.json").resolve())], cwd=cwd, env=env,
                        input=input_, text=True, encoding="utf8", capture_output=True, timeout=40)
                (directory / f"{name}-cli.txt").write_text(result.stdout + result.stderr, encoding="utf8")
                if result.returncode or "Reader 所选文字阅读段结束" not in result.stdout: raise AssertionError("CLI did not reach reading end")
        return {"pack_id": pack.metadata["pack_id"], "mode_scope": info["modes"], "strict_control_entry": type(strict).__name__,
                "strict_complete_game_timelines": 0, "strict_complete_named_missions": 0, "reader_complete_named_missions": 0,
                "strict_native_calls_attempted": len(native_calls), "strict_native_blocked": native_blocked,
                "reader_completed_selected_text_routes": len(runs), "unique_dialogue_ids": sorted(seen),
                "original_options_exercised": sorted(choices), "policy_actions_across_runs": dict(policies),
                "community_patches_applied": len(info.get("patches", {})), "runs": runs}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--discussion-pack", type=Path, default=Path("data/packs/hsr-reader.storypack"))
    p.add_argument("--mainline-pack", type=Path, default=Path("data/packs/hsr-mainline-reader.storypack"))
    p.add_argument("--output", type=Path, default=Path("data/m6-runtime-verification.json"))
    p.add_argument("--records", type=Path, default=Path("data/staging/m6-playback"))
    args = p.parse_args()
    routes = [[str(146010000 + x) for x in route] for route in product([204, 207, 212], [217, 219, 221], [227, 229, 232])]
    result = {"discussion": verify(args.discussion_pack, routes, args.records, "discussion"),
              "mainline_submission_100020111": verify(args.mainline_pack, [[]], args.records, "mainline"),
              "scope": "selected text/control reading segments; not complete native scheduling or full missions",
              "resource_index": {"reused_previous_inventory": True, "new_scans": 0,
                                 "original_references": 148, "exact_locations_from_m59": 142,
                                 "original_mainline_structurally_linked": 1, "gender_candidates_unresolved": 6,
                                 "discussion_resources_separate": 15}}
    # Cross-check all real routes, independently of the reconstruction compiler.
    first = {204: [205, 206], 207: [208, 209, 210, 211], 212: [213, 214]}
    second = {217: [218], 219: [220], 221: [222, 223]}
    third = {227: [228], 229: [230, 231], 232: [233, 234]}
    for run in result["discussion"]["runs"]:
        a, b, c = [int(x) - 146010000 for x in run["selection"]]
        expected = [202, 203] + first[a] + [215, 216] + second[b] + [224, 225, 226] + third[c] + [235, 236]
        assert run["dialogue_ids"] == [146010000 + x for x in expected]
    assert result["mainline_submission_100020111"]["runs"][0]["dialogue_ids"] == list(range(100020314, 100020328)) + [100020360, 100020361, 100020362]
    write(args.output, result)
    print(json.dumps({"discussion_routes": len(routes), "discussion_body_lines": len(result["discussion"]["unique_dialogue_ids"]),
                      "mainline_body_lines": len(result["mainline_submission_100020111"]["unique_dialogue_ids"]),
                      "strict_full_missions": 0, "report": str(args.output)}))


if __name__ == "__main__": main()
