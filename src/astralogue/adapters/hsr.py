"""Independent conservative lowering of observed HSR task sequences.

OnStartSequece is a set of concurrent sequences, NOT one story array.
TaskList and SimpleTalkList are ordered instruction streams. Only unique,
terminal custom-string handoffs are lowered into inter-sequence graph edges.
Timeline content and arbitrary game predicates cannot be reconstructed here.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from astralogue.model import Bundle, Diagnostic, Edge, Mission, Node, file_hash, load_json

# Audited presentation-only operations. Anything outside this exact allowlist
# remains blocking, including PlayTimeline (may contain otherwise absent speech).
PRESENTATION = {"LevelPerformanceInitialize", "AdvNpcFaceToPlayer", "CaptureLocalPlayer",
                "PlayScreenTransfer", "ActiveVirtualCamera", "WaitSecond", "CharacterHeadLookAt",
                "TriggerSound", "AdvEntityFaceTo"}
CONTROL = {"PlayAndWaitSimpleTalk", "PlaySimpleTalk", "WaitSimpleTalkFinish", "PlayOptionTalk", "WaitCustomString", "TriggerCustomString", "EndPerformance"}


def understood_shape(task: dict) -> bool:
    """Unknown control fields cannot be mistaken for cosmetic metadata."""
    typ = short(task)
    expected = {"PlayAndWaitSimpleTalk": {"$type", "SimpleTalkList"},
                "PlaySimpleTalk": {"$type", "SimpleTalkList"}, "WaitSimpleTalkFinish": {"$type"},
                "PlayOptionTalk": {"$type", "OptionList"},
                "WaitCustomString": {"$type", "CustomString"},
                "TriggerCustomString": {"$type", "CustomString"},
                "EndPerformance": {"$type"}}
    if typ not in expected or set(task) - expected[typ]: return False
    if typ in {"WaitCustomString", "TriggerCustomString"}:
        return isinstance(task.get("CustomString"), dict) and set(task["CustomString"]) == {"Value"}
    if typ == "PlayOptionTalk":
        options = task.get("OptionList")
        return isinstance(options, list) and all(isinstance(o, dict) and not (set(o) - {"$type", "TalkSentenceID", "OptionIconType", "TriggerCustomString"}) for o in options)
    if typ in {"PlayAndWaitSimpleTalk", "PlaySimpleTalk"}:
        talks = task.get("SimpleTalkList")
        return isinstance(talks, list) and all(isinstance(t, dict) and not (set(t) - {"TalkSentenceID", "ProtectTime", "TextSpeed"})
                                             and all(type(t[k]) in {int, float} for k in ["ProtectTime", "TextSpeed"] if k in t) for t in talks)
    return True


def short(task: dict) -> str:
    return str(task.get("$type", "")).removeprefix("RPG.GameCore.")


def presentation_only(task: dict) -> bool:
    def nested_control(obj: Any) -> bool:
        if isinstance(obj, dict):
            return any(k.endswith("TaskList") or "Predicate" in k or "Condition" in k or
                       (k == "IsDynamic" and v is True) or nested_control(v) for k, v in obj.items())
        if isinstance(obj, list): return any(nested_control(x) for x in obj)
        return False
    return short(task) in PRESENTATION and not nested_control(task)


def value(obj: Any) -> Any:
    return obj.get("Value") if isinstance(obj, dict) else obj


def rows(obj: Any, key: str) -> dict[str, dict]:
    result = {}
    items = obj.values() if isinstance(obj, dict) else obj
    if not isinstance(items, (list, type({}.values()))): raise ValueError("配置表必须是对象或数组")
    for row in items:
        if not isinstance(row, dict) or key not in row: continue
        rid = str(row[key])
        if rid in result: raise ValueError(f"配置表 ID 冲突: {key}={rid}")
        result[rid] = row
    return result


class HsrAdapter:
    def __init__(self, root: Path, languages: list[str]):
        self.root = root
        self.languages = languages
        self.b = Bundle(metadata={"game": "hsr", "adapter": "hsr-raw-v1", "languages": languages,
                                  "scope": "独立 Act/Discussion 会话；不推断任务内 Act 的全局顺序", "inputs": {}})
        self.maps: dict[str, dict] = {}
        self.talks: dict[str, dict] = {}

    def read(self, path: Path) -> Any:
        self.b.metadata["inputs"][path.relative_to(self.root).as_posix()] = file_hash(path)
        return load_json(path)

    def diag(self, code, message, mid=None, nid=None, severity="warning"):
        self.b.diagnostics.append(Diagnostic(code, message, severity, mid, nid))

    def hash_text(self, obj: Any) -> str | None:
        h = obj.get("Hash") if isinstance(obj, dict) else None
        if h is None: return None
        key = f"hsr:text:{h}"
        for lang, mapping in self.maps.items():
            if str(h) in mapping: self.b.text(key, mapping[str(h)], lang)
        return key

    def sentence(self, sid: Any) -> tuple[str | None, str | None]:
        row = self.talks.get(str(sid), {})
        return self.hash_text(row.get("TalkSentenceText")), self.hash_text(row.get("TextmapTalkSentenceName"))

    def load(self, pattern: str | None) -> Bundle:
        for lang in self.languages:
            self.maps[lang] = {}
            candidates = [self.root / "TextMap" / f"TextMap{lang}.json",
                          *sorted((self.root / "TextMap").glob(f"TextMap{lang}_*.json")),
                          self.root / "TextMap" / f"TextMapMain{lang}.json"]
            for p in candidates:
                if p.is_file():
                    for h, text in self.read(p).items():
                        previous = self.maps[lang].get(h)
                        if previous is not None and previous != text: raise ValueError(f"TextMap 冲突: {h}/{lang}")
                        self.maps[lang][h] = text
            if not self.maps[lang]: raise ValueError(f"缺少 TextMap: {lang}")
        self.talks = rows(self.read(self.root / "ExcelOutput/TalkSentenceConfig.json"), "TalkSentenceID")
        main, chapters = {}, {}
        for name, key in [("MainMission", "MainMissionID"), ("MissionChapterConfig", "ID")]:
            p = self.root / "ExcelOutput" / f"{name}.json"
            if p.exists():
                loaded = rows(self.read(p), key)
                if name == "MainMission": main = loaded
                else: chapters = loaded
        self.b.chapters = {}
        manifest = self.root / "source.json"
        if manifest.exists(): self.b.metadata["source"] = self.read(manifest)
        else:
            revision = "unknown"
            if (self.root / ".git").exists():
                try:
                    result = subprocess.run(["git", "-c", f"safe.directory={self.root.resolve().as_posix()}", "-C", str(self.root), "rev-parse", "HEAD"],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0: revision = result.stdout.strip()
                except (OSError, subprocess.TimeoutExpired): pass
            self.b.metadata["source"] = {"kind": "local-directory", "revision": revision}
        paths = set()
        for glob in ([pattern] if pattern else ["Config/Level/Mission/*/Act/*.json", "Story/Mission/*/*.json", "Story/Discussion/Mission/*/*.json"]):
            paths.update(p for p in self.root.glob(glob) if p.is_file() and not p.name.endswith(".layout.json"))
        for p in sorted(paths):
            rel = p.relative_to(self.root).as_posix()
            obj = self.read(p)
            if not isinstance(obj, dict) or "OnStartSequece" not in obj:
                self.diag("unrecognized_file", rel)
                self.b.source_refs.append({"file": rel, "pointer": "", "raw": obj})
                continue
            parts = rel.split("/")
            original = p.parent.parent.name if "Act" in parts else p.parent.name
            mid = "hsr:" + rel.removesuffix(".json")
            mr = main.get(original, {})
            chapter = str(mr.get("ChapterID", original if original == "TrainVisitor" else "unassigned"))
            if chapter not in self.b.chapters:
                cr = chapters.get(chapter, {})
                title = self.hash_text(cr.get("ChapterName"))
                if not title:
                    title = f"chapter:{chapter}"
                    for lang in self.languages:
                        self.b.text(title, "列车访客" if chapter == "TrainVisitor" else chapter, lang)
                self.b.chapters[chapter] = title
            title = self.hash_text(mr.get("Name"))
            title_key = f"title:{mid}"
            for lang in self.languages:
                name = self.b.texts.get(title, {}).get(lang, original)
                self.b.text(title_key, f"{name} / {p.stem}", lang)
            self.lower(obj, rel, Mission(mid, title_key, None, chapter, original))
        if not self.b.missions: raise ValueError("没有发现可导入的剧情文件；可使用 --pattern 指定实际路径")
        source = self.b.metadata["source"]
        expected = source.get("files", {}) if isinstance(source, dict) else {}
        for path, actual in self.b.metadata["inputs"].items():
            if path in expected and expected[path] != actual:
                self.diag("source_hash_mismatch", f"输入与来源清单不一致: {path}", severity="error")
        return self.b

    def lower(self, obj: dict, rel: str, mission: Mission) -> None:
        mid = mission.id
        self.b.missions.append(mission)
        self.b.source_refs.append({"file": rel, "pointer": "", "mission": mid, "raw": obj})
        seqs = obj.get("OnStartSequece", [])
        if not isinstance(seqs, list): raise ValueError(f"{rel}: OnStartSequece 不是数组")
        active, waiters, roots = {}, {}, []
        edge_counts: dict[str, int] = {}
        for si, seq in enumerate(seqs):
            tasks = seq.get("TaskList", []) if isinstance(seq, dict) else []
            # WaitPerformanceEnd + FinishLevelGraph is a known lifecycle observer;
            # EndPerformance already terminates this offline session.
            kinds = [short(t) for t in tasks]
            lifecycle = kinds == ["WaitPerformanceEnd", "FinishLevelGraph"] and all(set(t) == {"$type"} for t in tasks)
            if lifecycle or (tasks and all(presentation_only(t) for t in tasks)):
                self.diag("presentation_observer", f"保留但不执行并行表现/生命周期序列 {si}", mid, severity="info")
                continue
            if not tasks: continue
            prefix = f"{mid}:s{si}"
            active[si] = (prefix, tasks)
            if short(tasks[0]) == "WaitCustomString":
                ev = value(tasks[0].get("CustomString"))
                if isinstance(ev, str): waiters.setdefault(ev, []).append(prefix + ":t0")
            else: roots.append(prefix + ":t0")
        # Never concatenate concurrent sequences or pick one by file order.
        extra_sequences = any(v for k, v in obj.items() if k not in {"OnStartSequece", "OnInitSequece"} and ("Sequece" in k or "Sequence" in k))
        extra_seq_fields = any(isinstance(seq, dict) and set(seq) - {"TaskList"} for seq in seqs)
        if len(roots) == 1 and not obj.get("OnInitSequece") and not extra_sequences and not extra_seq_fields:
            mission.entry = roots[0]
        else:
            self.diag("ambiguous_entry", "入口并发或存在尚未支持的 OnInitSequece", mid, severity="error")
        for si, (prefix, tasks) in active.items():
            for ti, task in enumerate(tasks):
                nid = f"{prefix}:t{ti}"
                typ = short(task)
                if typ in CONTROL and not understood_shape(task):
                    typ = "UnsupportedControlShape:" + typ
                next_id = f"{prefix}:t{ti + 1}" if ti + 1 < len(tasks) else None
                pointer = f"/OnStartSequece/{si}/TaskList/{ti}"
                self.b.source_refs.append({"file": rel, "pointer": pointer, "node": nid,
                                           "original_id": task.get("TalkSentenceID"), "raw": task})
                n = Node(nid, mid, "unknown", data={"operation": typ})
                self.b.nodes.append(n)

                def link(src: str, dst: str, kind="next", **kw):
                    count = edge_counts.get(src, 0)
                    edge_counts[src] = count + 1
                    self.b.edges.append(Edge(f"{src}:e{count}", src, dst, kind, **kw))

                def handoff(event: Any) -> str | None:
                    targets = waiters.get(event, []) if isinstance(event, str) else []
                    if len(targets) != 1:
                        self.diag("event_target", f"事件 {event!r} 的本文件监听者数量为 {len(targets)}", mid, nid, "error")
                        return None
                    return targets[0]

                if presentation_only(task):
                    n.kind = "noop"
                    n.data["reason"] = "audited-presentation-only"
                    self.diag("presentation_omitted", typ, mid, nid, "info")
                elif typ in {"PlayAndWaitSimpleTalk", "PlaySimpleTalk"}:
                    talks = task.get("SimpleTalkList")
                    awaited = typ == "PlayAndWaitSimpleTalk" or (next_id is not None and short(tasks[ti + 1]) == "WaitSimpleTalkFinish" and understood_shape(tasks[ti + 1]))
                    if awaited and isinstance(talks, list) and talks:
                        n.kind = "noop"
                        prev = nid
                        for i, talk in enumerate(talks):
                            did = f"{nid}:line{i}"
                            sid = talk.get("TalkSentenceID")
                            text, speaker = self.sentence(sid)
                            self.b.nodes.append(Node(did, mid, "dialogue", text, speaker, {"sentence_id": sid}))
                            self.b.source_refs.append({"file": rel, "pointer": f"{pointer}/SimpleTalkList/{i}", "node": did, "original_id": sid, "raw": talk})
                            link(prev, did); prev = did
                        if next_id: link(prev, next_id)
                        else: self.diag("missing_continuation", "台词序列末尾没有显式结束或事件交接", mid, prev, "error")
                        continue
                elif typ == "WaitSimpleTalkFinish" and ti > 0 and short(tasks[ti - 1]) == "PlaySimpleTalk" and understood_shape(tasks[ti - 1]):
                    n.kind = "noop"
                elif typ == "WaitCustomString":
                    event = value(task.get("CustomString"))
                    if isinstance(event, str):
                        n.kind = "wait"; n.data = {"event": event, "consume": True, "internal": True}
                elif typ == "TriggerCustomString" and next_id is None:
                    event = value(task.get("CustomString")); target = handoff(event)
                    if target:
                        n.kind = "emit"; n.data = {"event": event}; link(nid, target)
                    continue
                elif typ == "PlayOptionTalk" and next_id is None:
                    options = task.get("OptionList")
                    if isinstance(options, list) and options:
                        n.kind = "choice"; n.data["option_events"] = {}
                        for i, option in enumerate(options):
                            opt_id = str(i + 1)
                            text, _ = self.sentence(option.get("TalkSentenceID"))
                            event = option.get("TriggerCustomString"); target = handoff(event)
                            if target is None:
                                target = f"{nid}:unresolved{i}"
                                self.b.nodes.append(Node(target, mid, "unknown", data={"raw_option": option}))
                            n.data["option_events"][opt_id] = event
                            # Keep duplicate destinations: distinct options are distinct edges.
                            link(nid, target, "option", text=text, value=opt_id)
                        continue
                elif typ == "EndPerformance":
                    n.kind = "end"
                    continue
                if n.kind == "unknown":
                    self.diag("unsupported_raw", f"不支持的操作或并发控制形态: {typ}", mid, nid, "error")
                elif next_id:
                    link(nid, next_id)
                else:
                    self.diag("missing_continuation", "未证明序列结束等于剧情结束", mid, nid, "error")
