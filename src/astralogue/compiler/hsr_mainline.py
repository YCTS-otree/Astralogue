"""HSR task graphs and mission linker; the Runtime contains no HSR opcodes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astralogue import __version__
from astralogue.adapters.hsr import HsrAdapter, presentation_only, rows, short, understood_shape, value
from astralogue.hsr.manifest import create_manifest
from astralogue.hsr.sources import ResourceError, Sources, performance_index
from astralogue.model import Bundle, Diagnostic, Edge, Mission, Node, digest


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for val in obj.values(): yield from walk(val)
    elif isinstance(obj, list):
        for val in obj: yield from walk(val)


class MainlineCompiler:
    def __init__(self, root: Path, lang: str = "CHS", supplements: list[Path] | None = None,
                 native_bundles: list[Bundle] | None = None) -> None:
        self.sources = Sources([root, *(supplements or [])])
        self.manifest = create_manifest(root, lang)
        self.lang = lang
        self.b = Bundle(metadata={"game": "hsr", "version": __version__, "parser_version": "hsr-mainline-1",
                                  "languages": [lang], "sources": self.sources.versions,
                                  "source_priority": list(range(len(self.sources.roots))),
                                  "imported_at_utc": datetime.now(timezone.utc).isoformat(),
                                  "mission_initial_variables": {}, "mission_manifest": self.manifest,
                                  "mission_labels": {}, "resource_blobs": {}, "hsr_text_index": {}, "required_capabilities": ["call-return-v1"]}, chapters={})
        self.reader = HsrAdapter(root, [lang]); self.reader.b = self.b
        mapping = {}
        for rel in [f"TextMap/TextMap{lang}.json", f"TextMap/TextMapMain{lang}.json"]:
            if self.sources.exists(rel):
                for h, text in self.sources.read(rel).items():
                    if h in mapping and mapping[h] != text: raise ResourceError(f"TextMap 冲突: {h}")
                    mapping[h] = text
        if not mapping: raise ResourceError(f"缺少 TextMap {lang}")
        self.reader.maps = {lang: mapping}
        self.reader.talks = rows(self.sources.read("ExcelOutput/TalkSentenceConfig.json"), "TalkSentenceID")
        self.performance = performance_index(self.sources)
        self.nodes = {}
        self.assets = {}
        self.metrics = {}
        self.current = ""
        self.serial = Counter()
        self.subfragments = []
        self.pending_returns = []
        self.native_entries = {}
        for native in native_bundles or []:
            source = native.metadata.get("source", {})
            expected = self.manifest["source"]
            if expected.get("revision") in {None, "unknown"} or source.get("revision") != expected.get("revision") or source.get("game_version") != expected.get("game_version"):
                raise ResourceError("Native IR 来源版本不匹配")
            known = {n.id: n for n in native.nodes}
            for name, target in native.metadata.get("native_timeline_entries", {}).items():
                if name in self.native_entries: raise ResourceError("Native Timeline 注册冲突")
                if not isinstance(name, str) or not isinstance(target, dict) or not isinstance(target.get("returns"), list):
                    raise ResourceError("Native Timeline 注册结构不完整")
                if target.get("entry") not in known or any(ret not in known or known[ret].kind != "return" for ret in target.get("returns", [])):
                    raise ResourceError("Native Timeline 入口/返回引用缺失")
                if target.get("schedule_status") not in {"BLOCKED", "STATICALLY_COMPILED"}:
                    raise ResourceError("Native Timeline 调度状态未知")
                self.native_entries[name] = target
            for key, langs in native.texts.items():
                if self.lang not in langs: raise ResourceError("Native IR 语言未解析")
                for lang_name, text in langs.items(): self.b.text(key, text, lang_name)
            for key, title in native.chapters.items():
                if key in self.b.chapters and self.b.chapters[key] != title: raise ResourceError("Native chapter 冲突")
                self.b.chapters[key] = title
            for node in native.nodes:
                if node.id in self.nodes: raise ResourceError("Native node 冲突")
                self.nodes[node.id] = node
            self.b.nodes.extend(native.nodes); self.b.edges.extend(native.edges); self.b.missions.extend(native.missions)
            self.b.source_refs.extend(native.source_refs); self.b.diagnostics.extend(native.diagnostics)
            for mission in native.missions:
                self.b.metadata["mission_labels"][mission.id] = {"category": "NATIVE_TIMELINE", "scope": "NATIVE_LIBRARY"}
            for key in ("native_evidence", "logical_clocks"):
                store = self.b.metadata.setdefault(key, {})
                for name, record in native.metadata.get(key, {}).items():
                    if name in store and store[name] != record: raise ResourceError("Native 元数据冲突")
                    store[name] = record
        self.b.metadata["native_timeline_entries"] = self.native_entries

    def node(self, nid: str, kind: str, data: dict | None = None, text: str | None = None, speaker: str | None = None) -> str:
        if nid in self.nodes: raise ValueError(f"编译器节点冲突: {nid}")
        n = Node(nid, self.current, kind, text, speaker, data or {})
        self.nodes[nid] = n; self.b.nodes.append(n)
        return nid

    def edge(self, src: str, dst: str, kind: str = "next", **kw) -> None:
        i = self.serial[src]; self.serial[src] += 1
        self.b.edges.append(Edge(f"{src}:e{i}", src, dst, kind, **kw))

    def diag(self, code: str, message: str, node: str | None = None, severity: str = "error") -> None:
        self.b.diagnostics.append(Diagnostic(code, message, severity, self.current, node))

    def unknown(self, nid: str, reason: str, raw: Any = None) -> str:
        self.diag("hsr_unresolved", reason, nid)
        if isinstance(raw, dict) and "$type" in raw: self.metric()["unsupported"][short(raw)] += 1
        return self.node(nid, "unknown", {"operation": reason, "raw": raw})

    def metric(self) -> dict:
        return self.metrics.setdefault(self.current, {"dialogue_references": [], "dialogue_text_keys": [], "timeline_references": [],
            "option_references": 0, "option_edges": 0, "resources": [], "missing_resources": [], "unsupported": Counter()})

    def record(self, obj: Any, rel: str) -> None:
        ids = [x["TalkSentenceID"] for x in walk(obj) if "TalkSentenceID" in x]
        self.metric()["dialogue_references"].extend(ids)
        for sid in ids:
            text, speaker = self.reader.sentence(sid)
            self.metric()["dialogue_text_keys"].append(text)
            self.b.metadata["hsr_text_index"][str(sid)] = {"text": text, "speaker": speaker}
        for task in walk(obj):
            if short(task) == "PlayOptionTalk": self.metric()["option_references"] += len(task.get("OptionList", []))
        self.metric()["resources"].append(rel)

    def resource(self, logical: str) -> tuple[str, list[str]]:
        key = self.current, logical
        if key in self.assets: return self.assets[key]
        base = f"{self.current}:r{digest(logical)[:16]}"
        try:
            obj = self.sources.read(logical); self.record(obj, logical)
        except ResourceError as ex:
            self.metric()["missing_resources"].append({"path": logical, "reason": str(ex)})
            result = self.unknown(base, str(ex)), []
            self.assets[key] = result; return result
        if not isinstance(obj, dict) or not isinstance(obj.get("OnStartSequece"), list):
            result = self.unknown(base, "未知控制资源结构", obj), []
            self.assets[key] = result; return result
        entry, returns = base + ":entry", []
        self.assets[key] = entry, returns
        self.node(entry, "noop")
        seqs = obj["OnStartSequece"]
        active, listeners, roots = [], {}, []
        for si, seq in enumerate(seqs):
            tasks = seq.get("TaskList", [])
            kinds = [short(t) for t in tasks]
            observer = bool(tasks and kinds[0] == "WaitPerformanceEnd" and kinds[-1] == "FinishLevelGraph" and all(presentation_only(t) for t in tasks[1:-1]))
            if observer or (tasks and all(presentation_only(t) for t in tasks)): continue
            if not tasks: continue
            sid = f"{base}:s{si}"
            active.append((si, sid, tasks))
            if short(tasks[0]) == "WaitCustomString" and understood_shape(tasks[0]) and isinstance(value(tasks[0].get("CustomString")), str):
                listeners.setdefault(value(tasks[0].get("CustomString")), []).append(sid + ":t0")
            else: roots.append(sid + ":t0")
        extra = any(v for k, v in obj.items() if k not in {"OnInitSequece", "OnStartSequece", "Type"} and ("Sequece" in k or "Sequence" in k))
        if len(roots) == 1 and not obj.get("OnInitSequece") and not extra and all(not (set(s) - {"TaskList", "Order"}) for s in seqs):
            self.edge(entry, roots[0])
        else:
            self.nodes[entry].kind = "unknown"
            self.nodes[entry].data = {"operation": "并发或外部事件入口未解决", "candidate_roots": roots}
            self.diag("hsr_entry", "未推测并发序列/外部触发器的入口", entry)
        for si, sid, tasks in active:
            tail = self.node(sid + ":return", "return"); returns.append(tail)
            self.task_list(tasks, sid, tail, listeners, logical, f"/OnStartSequece/{si}/TaskList")
        # Acquisition and text preservation are independent of whether a call
        # can be executed. A blocked parent must not discard its literal callees.
        for task in walk(obj):
            if short(task) == "TriggerPerformance" and isinstance(task.get("PerformanceType"), str):
                for path in sorted(self.performance.get((task["PerformanceType"], str(task.get("PerformanceID"))), set())):
                    self.resource(path)
            elif short(task) == "PlayTimeline" and isinstance(task.get("TimelineName"), str):
                try:
                    path, _ = self.sources.timeline(task["TimelineName"]); self.resource(path)
                except ResourceError: pass  # the actual opcode has its own diagnostic
        return entry, returns

    def invoke(self, nid: str, target: tuple[str, list[str]], continuation: str) -> None:
        self.node(nid, "call")
        entry, returns = target
        self.edge(nid, entry, "call"); self.edge(nid, continuation)
        self.pending_returns.append((returns, continuation))

    def cosmetic(self, task: dict) -> bool:
        if any(k.endswith("TaskList") or "Predicate" in k or "Condition" in k or k.startswith("On") or k in {"Execute", "Callback"} for obj in walk(task) for k in obj):
            return False
        if presentation_only(task): return True
        typ = short(task)
        if typ in {"LockPlayerControl", "UnLockPlayerControl", "ClearTalkUI", "ShowTalkUI", "OverrideEndTransferColor", "SetAudioEmotionState"}:
            return not any("TaskList" in k or "Predicate" in k for x in walk(task) for k in x)
        if typ == "PerformanceTransition":
            keys = {"$type", "SwitchInTime", "SwitchOutTime", "CreateNpcList", "CaptureNpcList", "DestroyNpcList", "ActiveVirtualCamera", "SwitchCharacterAnchor", "AdvNpcFaceToPlayer"}
            return not (set(task) - keys) and not any(task.get(k) for k in ["CreateNpcList", "CaptureNpcList", "DestroyNpcList"]) and not any("TaskList" in k or "Predicate" in k for x in walk(task) for k in x)
        if typ == "PropMoveTo":
            return not (set(task) - {"$type", "Duration", "AreaName", "AnchorName", "TargetType"}) and task.get("Duration", {}).get("IsDynamic") is False
        return False

    def predicate(self, obj: Any) -> dict | None:
        if isinstance(obj, dict) and short(obj) == "ByCompareSubMissionState" and obj.get("SubMissionState") == "Finish":
            if set(obj) <= {"$type", "SubMissionID", "SubMissionState"}:
                return {"eq": [{"var": f"hsr:sub:{obj['SubMissionID']}:finished"}, True]}
        return None

    def task_list(self, tasks: list[dict], prefix: str, tail: str, listeners: dict, logical: str, pointer: str) -> None:
        for ti, task in enumerate(tasks):
            nid = f"{prefix}:t{ti}"
            nxt = f"{prefix}:t{ti + 1}" if ti + 1 < len(tasks) else tail
            typ = short(task)
            self.b.source_refs.append({"node": nid, "file": logical, "pointer": f"{pointer}/{ti}"})
            if self.cosmetic(task):
                self.node(nid, "noop", {"reason": "audited-hsr-presentation", "operation": typ}); self.edge(nid, nxt)
            elif typ in {"PlayAndWaitSimpleTalk", "PlaySimpleTalk", "PlayMissionTalk"}:
                awaited = typ != "PlaySimpleTalk" or (ti + 1 < len(tasks) and short(tasks[ti + 1]) == "WaitSimpleTalkFinish")
                if typ == "PlayMissionTalk": awaited = ti + 1 < len(tasks) and short(tasks[ti + 1]) == "WaitCustomString"
                if set(task) - {"$type", "SimpleTalkList", "BlackMask"} or not awaited or not isinstance(task.get("SimpleTalkList"), list) or ("BlackMask" in task and not isinstance(task["BlackMask"], bool)):
                    self.unknown(nid, f"不支持的对话控制形态 {typ}", task); continue
                self.node(nid, "noop"); prev = nid
                for i, talk in enumerate(task["SimpleTalkList"]):
                    if set(talk) - {"TalkSentenceID", "ProtectTime", "TextSpeed"} or any(type(talk[k]) not in {int, float} for k in ["ProtectTime", "TextSpeed"] if k in talk):
                        did = self.unknown(f"{nid}:l{i}", "未知台词控制字段", talk)
                    else:
                        text, speaker = self.reader.sentence(talk.get("TalkSentenceID"))
                        did = self.node(f"{nid}:l{i}", "dialogue", {"sentence_id": talk.get("TalkSentenceID")}, text, speaker)
                    self.edge(prev, did); prev = did
                self.edge(prev, nxt)
            elif typ == "WaitSimpleTalkFinish" and understood_shape(task) and ti > 0 and short(tasks[ti - 1]) == "PlaySimpleTalk":
                self.node(nid, "noop"); self.edge(nid, nxt)
            elif typ == "TriggerPerformance":
                ptype = task.get("PerformanceType")
                candidates = self.performance.get((ptype, str(task.get("PerformanceID"))), set()) if isinstance(ptype, str) else set()
                mask = task.get("MaskConfig", {})
                valid_mask = isinstance(mask, dict) and not (set(mask) - {"UseExcelData", "StartBlack", "EndBlack", "StartBlackTime", "EndBlackTime"})
                if len(candidates) == 1 and valid_mask and not task.get("ValueSource") and not (set(task) - {"$type", "PerformanceType", "PerformanceID", "ValueSource", "MaskConfig"}):
                    self.invoke(nid, self.resource(next(iter(candidates))), nxt)
                else: self.unknown(nid, "Performance 引用冲突、缺失或动态参数", task)
            elif typ == "PlayTimeline":
                name = task.get("TimelineName"); rec = {"name": name, "resolved": False}
                self.metric()["timeline_references"].append(rec)
                try:
                    if not isinstance(name, str) or task.get("Parameters") or set(task) - {"$type", "TimelineName", "Type", "Parameters"}: raise ResourceError("动态 Timeline 参数尚未解析")
                    if name in self.native_entries:
                        target = self.native_entries[name]
                        self.invoke(nid, (target["entry"], target["returns"]), nxt)
                        rec.update(resolved=True, native_graph_linked=True, native_schedule_status=target["schedule_status"])
                        if target["schedule_status"] == "BLOCKED": self.diag("native_schedule_blocked", "原生资源已链接，调度语义仍受阻", nid)
                        continue
                    resolved, _ = self.sources.timeline(name)
                    self.invoke(nid, self.resource(resolved), nxt); rec["resolved"] = True
                except ResourceError as ex:
                    self.metric()["missing_resources"].append({"path": name, "reason": str(ex)})
                    self.unknown(nid, str(ex), task)
            elif typ == "EndPerformance" and set(task) == {"$type"}:
                self.node(nid, "noop"); self.edge(nid, tail)
            elif typ == "FinishPerformanceMission" and isinstance(task.get("Key"), str) and set(task) <= {"$type", "Key"}:
                self.node(nid, "emit", {"event": "hsr:finish:" + task["Key"]}); self.edge(nid, nxt)
            elif typ == "WaitCustomString" and understood_shape(task) and isinstance(value(task.get("CustomString")), str):
                event = value(task.get("CustomString"))
                self.node(nid, "wait", {"event": event, "consume": True, "internal": bool(listeners.get(event))}); self.edge(nid, nxt)
            elif typ == "TriggerCustomString" and understood_shape(task) and isinstance(value(task.get("CustomString")), str):
                event = value(task.get("CustomString")); matches = listeners.get(event, [])
                if len(matches) == 1 and ti == len(tasks) - 1:
                    self.node(nid, "emit", {"event": event}); self.edge(nid, matches[0])
                elif not matches:
                    self.node(nid, "emit", {"event": event}); self.edge(nid, nxt)
                    self.diag("external_event", "外部事件已记录，未假设游戏世界的处理结果", nid, "warning")
                else: self.unknown(nid, "并发事件分发尚未解决", task)
            elif typ == "PlayOptionTalk" and ti == len(tasks) - 1 and understood_shape(task):
                self.node(nid, "choice", {"option_events": {}})
                for i, option in enumerate(task.get("OptionList", [])):
                    val = str(i + 1); event = option.get("TriggerCustomString"); matches = listeners.get(event, []) if isinstance(event, str) else []
                    target = matches[0] if len(matches) == 1 else self.unknown(f"{nid}:missing{i}", "选项没有唯一事件目标", option)
                    text, _ = self.reader.sentence(option.get("TalkSentenceID"))
                    self.nodes[nid].data["option_events"][val] = event
                    self.edge(nid, target, "option", text=text, value=val)
                    if len(matches) == 1: self.metric()["option_edges"] += 1
            elif typ == "PredicateTaskList" and (expr := self.predicate(task.get("Predicate"))) is not None and set(task) <= {"$type", "Predicate", "SuccessTaskList", "FailedTaskList"}:
                self.node(nid, "branch")
                for flag, key in [(True, "SuccessTaskList"), (False, "FailedTaskList")]:
                    nested = task.get(key, []); target = f"{nid}:{key}:t0" if nested else nxt
                    self.edge(nid, target, "condition", condition=expr if flag else {"not": expr})
                    self.task_list(nested, f"{nid}:{key}", nxt, listeners, logical, f"{pointer}/{ti}/{key}")
            elif typ == "SetMissionCustomValue" and set(task) <= {"$type", "SubmissionID", "MissionCustomValue", "CustomValue"}:
                spec = task.get("MissionCustomValue", {})
                if not (set(spec) - {"Name", "ValidValueParamList"}) and isinstance(spec.get("Name"), str) and task.get("CustomValue") in spec.get("ValidValueParamList", []):
                    self.node(nid, "set", {"var": f"hsr:custom:{task.get('SubmissionID')}:{spec['Name']}", "value": task["CustomValue"]}); self.edge(nid, nxt)
                else: self.unknown(nid, "未知任务状态修改结构", task)
            else:
                self.unknown(nid, f"未支持指令 {typ}", task)

    def compile_mission(self, record: dict) -> None:
        mid = "hsr:mission:" + record["id"]; self.current = mid
        chapter = str(record.get("chapter") or "unknown")
        self.b.chapters.setdefault(chapter, self.b.text("hsr:chapter:" + chapter, record.get("chapter_title") or chapter, self.lang))
        title = self.b.text(mid + ":title", record.get("title") or record["id"], self.lang)
        mission = Mission(mid, title, None, chapter, record["id"]); self.b.missions.append(mission)
        self.b.metadata["mission_labels"][mid] = {"category": record["category"] if record["named_story_candidate"] else "TRAILBLAZE_INTERNAL",
            "scope": "MISSION", "original_id": record["id"], "classification": record["category"],
            "entry_context": "selected mission is accepted; TakeParam world prerequisites are not asserted"}
        self.metric(); subs = record["submissions"]
        try:
            for key in ["info", "partial"]:
                logical = record["provenance"][key]
                if self.sources.exists(logical):
                    self.sources.read(logical)
                    actual = self.sources.records[logical]["sha256"]
                    if record["provenance"][key + "_sha256"] != actual: raise ResourceError("任务定义在导入过程中发生变化")
        except ResourceError as ex:
            mission.entry = self.unknown(mid + ":source-conflict", str(ex))
            return
        if record["errors"] or not record["entries"] or not record["finish_submissions"] or not any(s["local"] for s in subs):
            paths = [s["resource"] for s in subs if s["resource"] and not s["local"]]
            self.metric()["missing_resources"].extend({"path": p, "reason": "not acquired"} for p in paths or [record["provenance"]["info"]])
            mission.entry = self.unknown(mid + ":unavailable", "任务入口/完成定义或可执行资源缺失", record["errors"]); return
        done = {s["id"]: f"hsr:sub:{s['id']}:finished" for s in subs}
        self.b.metadata["mission_initial_variables"][mid] = {v: False for v in done.values()}
        scheduler = self.node(mid + ":schedule", "branch"); mission.entry = scheduler
        end = self.node(mid + ":end", "end", {"original_mission_id": record["id"], "finish_submissions": record["finish_submissions"]})
        if not all(sid in done for sid in record["finish_submissions"]):
            self.nodes[scheduler].kind = "unknown"; self.nodes[scheduler].data = {"operation": "完成子任务不属于任务定义"}
            self.diag("mission_finish_reference", "完成条件引用缺失", scheduler); return
        completed = {"all": [{"eq": [{"var": done[sid]}, True]} for sid in record["finish_submissions"]]}
        self.edge(scheduler, end, "condition", condition=completed)
        for sub in subs:
            sid = sub["id"]; base = mid + ":sub:" + sid
            deps = [str(x) for x in sub["dependencies"]]
            if sid in record["entries"]: ready = True
            elif sub["take_type"] in {"AnySequence", "MultiSequence"} and deps and all(d in done for d in deps):
                ready = {"any" if sub["take_type"] == "AnySequence" else "all": [{"eq": [{"var": done[d]}, True]} for d in deps]}
            else:
                ready = {"event": f"external:sub:{sid}:eligible"}
                self.diag("mission_external_eligibility", f"子任务 {sid} 需要游戏世界的开始条件", scheduler, "warning")
            cond = {"all": [{"not": completed}, {"eq": [{"var": done[sid]}, False]}, ready]}
            self.edge(scheduler, base + ":call", "condition", condition=cond)
            checkpoint = base + ":check"
            target = self.resource(sub["resource"]) if sub["resource"] else (self.unknown(base + ":missing", "子任务没有 MissionJsonPath"), [])
            if sub["resource"] and self.sources.exists(sub["resource"]):
                self.subfragments.append((mid, record, sub, target))
            self.invoke(base + ":call", target, checkpoint)
            self.node(checkpoint, "branch")
            if sub["finish_type"] == "Talk" and sub["finish_key"] and sub["raw"].get("ParamType") == "Equal" and sub["raw"].get("Progress") == 1:
                expr = {"event": "hsr:finish:" + sub["finish_key"]}
                success = self.node(base + ":done", "set", {"var": done[sid], "value": True}); self.edge(success, scheduler)
                failure = self.unknown(base + ":unfinished", "脚本未满足实际 Talk 完成条件", sub["raw"])
                self.edge(checkpoint, success, "condition", condition=expr)
                self.edge(checkpoint, failure, "condition", condition={"not": expr})
                if sub["raw"].get("FinishActionList"):
                    for action in walk(sub["raw"]["FinishActionList"]):
                        if "$type" in action: self.metric()["unsupported"][short(action)] += 1
                    self.nodes[success].kind = "unknown"; self.nodes[success].data = {"operation": "FinishActionList 尚未解析", "raw": sub["raw"]["FinishActionList"]}
                    self.diag("finish_actions", "未跳过子任务完成动作", success)
            else:
                self.nodes[checkpoint].kind = "wait"
                self.nodes[checkpoint].data = {"event": f"external:sub:{sid}:finish:{sub['finish_type']}"}
                target = self.unknown(base + ":world", "世界状态完成语义尚未解析", sub["raw"])
                self.edge(checkpoint, target)

    def compile(self, categories: tuple[str, ...] = ("TRAILBLAZE",), fragments: bool = True) -> Bundle:
        for record in self.manifest["missions"]:
            if record["category"] in categories: self.compile_mission(record)
        if fragments:
            for parent, record, sub, target in self.subfragments:
                if sub["finish_type"] != "Talk" or not sub["finish_key"] or sub["raw"].get("ParamType") != "Equal" or sub["raw"].get("Progress") != 1: continue
                mid = parent + ":submission:" + sub["id"]; self.current = mid
                owner = next(m for m in self.b.missions if m.id == parent)
                title = self.b.text(mid + ":title", self.b.texts[owner.title][self.lang] + " / 子任务 " + sub["id"], self.lang)
                entry, check = mid + ":call", self.node(mid + ":check", "branch")
                end = self.node(mid + ":end", "end", {"scope": "SUBMISSION_FRAGMENT", "finish_key": sub["finish_key"]})
                failure = self.unknown(mid + ":unfinished", "子任务脚本未产生已声明的完成事件", sub["raw"])
                expr = {"event": "hsr:finish:" + sub["finish_key"]}
                self.edge(check, end, "condition", condition=expr)
                self.edge(check, failure, "condition", condition={"not": expr})
                self.b.missions.append(Mission(mid, title, entry, owner.chapter, owner.original_id))
                self.b.metadata["mission_labels"][mid] = {"category": "TRAILBLAZE_SUBMISSION", "scope": "SUBMISSION_FRAGMENT",
                    "parent": parent, "resource": sub["resource"], "sub_id": sub["id"], "finish_key": sub["finish_key"],
                    "entry_context": "selected submission is already active; world prerequisites are not asserted"}
                self.invoke(entry, target, check)
            for (parent, logical), target in list(self.assets.items()):
                if "/Mission_" in logical or not self.sources.exists(logical): continue
                obj = self.sources.cache.get(logical, {})
                if not any("TalkSentenceID" in x or short(x) == "PlayOptionTalk" for x in walk(obj)): continue
                fragment = parent + ":fragment:" + digest(logical)[:16]; self.current = fragment
                owner = next(m for m in self.b.missions if m.id == parent)
                title = self.b.text(fragment + ":title", self.b.texts[owner.title][self.lang] + " / 片段 " + Path(logical).stem, self.lang)
                entry = fragment + ":call"; end = self.node(fragment + ":end", "end", {"scope": "PERFORMANCE_FRAGMENT"})
                self.b.missions.append(Mission(fragment, title, entry, owner.chapter, owner.original_id))
                self.b.metadata["mission_labels"][fragment] = {"category": "TRAILBLAZE_FRAGMENT", "scope": "PERFORMANCE_FRAGMENT",
                    "parent": parent, "resource": logical, "entry_context": "explicit performance entry; world prerequisites are not asserted"}
                self.invoke(entry, target, end)
        bound = set()
        for returns, continuation in self.pending_returns:
            for ret in returns:
                if (ret, continuation) not in bound:
                    self.edge(ret, continuation, "return"); bound.add((ret, continuation))
        for rel, record in self.sources.records.items():
            if rel.startswith(("ExcelOutput/", "TextMap/")): continue
            self.b.metadata["resource_blobs"].setdefault(record["sha256"], record["raw"])
            self.b.source_refs.append({k: v for k, v in record.items() if k != "raw"})
        self.b.metadata["inputs"] = self.sources.inputs
        self.b.metadata["source"] = self.manifest["source"]
        for metric in self.metrics.values():
            metric["unsupported"] = dict(metric["unsupported"])
            metric["resolved_dialogue_references"] = sum(
                bool((key := self.reader.sentence(sid)[0]) is not None and self.lang in self.b.texts.get(key, {}))
                for sid in metric["dialogue_references"])
        self.b.metadata["hsr_metrics"] = self.metrics
        self.b.metadata["source_conflicts"] = self.sources.conflicts
        for record in self.manifest["missions"]:
            metric = self.metrics.get("hsr:mission:" + record["id"])
            if metric is not None:
                record["resolved_control_resources"] = metric["resources"]
                record["timeline_references"] = metric["timeline_references"]
                record["control_parse_status"] = "PARSED_WITH_GAPS" if metric["missing_resources"] or metric["unsupported"] else "PARSED"
                record["completeness"] = "NOT_RUNTIME_VERIFIED"
        return self.b
