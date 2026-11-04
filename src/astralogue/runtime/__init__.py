"""UI-free narrative runtime. Only StoryPack is an input dependency."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any

from astralogue.conditions import ConditionError, evaluate
from astralogue.model import Edge, KINDS, canonical
from astralogue.storypack import StoryPack


@dataclass(frozen=True)
class DialogueEvent:
    node: str
    speaker: str
    text: str


@dataclass(frozen=True)
class Option:
    value: str
    text: str
    target: str


@dataclass(frozen=True)
class ChoiceEvent:
    node: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class EndEvent:
    node: str


@dataclass(frozen=True)
class BlockedEvent:
    node: str | None
    reason: str
    code: str = "blocked"


@dataclass(frozen=True)
class DiagnosticEvent:
    node: str
    code: str
    message: str


Event = DialogueEvent | ChoiceEvent | EndEvent | BlockedEvent | DiagnosticEvent


@dataclass
class State:
    mission: str
    node: str | None
    variables: dict[str, Any] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    frames: list[dict[str, str]] = field(default_factory=list)


class Runtime:
    def __init__(self, pack: StoryPack, mission: str, lang: str = "CHS"):
        self.pack = pack
        self.lang = lang
        m = pack.mission(mission)
        self.state = State(mission, m["entry"])
        initial = pack.metadata.get("initial_variables", {})
        if not isinstance(initial, dict): raise ValueError("初始变量必须是对象")
        self.state.variables = deepcopy(initial)
        self.state.variables.update(deepcopy(pack.metadata.get("mission_initial_variables", {}).get(mission, {})))
        self.history: list[dict] = []

    def snapshot(self) -> dict:
        return deepcopy(asdict(self.state))

    def _eligible(self, edges: list[Edge]) -> list[Edge]:
        return [e for e in edges if e.condition is None or evaluate(e.condition, self.state.variables, set(self.state.events))]

    def _single(self, nid: str) -> Edge:
        edges = self.pack.edges(nid)
        if len(edges) != 1 or edges[0].kind != "next" or edges[0].condition is not None:
            raise ValueError("节点缺少唯一的无条件 next 关系")
        target = self.pack.node(edges[0].target)
        if target.mission != self.state.mission and self.pack.node(nid).kind not in {"enter", "exit"}:
            raise ValueError("未经 enter/exit 的跨任务跳转")
        return edges[0]

    def _move(self, edge: Edge, transition: bool = False):
        target = self.pack.node(edge.target)
        if target.mission != self.state.mission and not transition:
            raise ValueError("未经 enter/exit 的跨任务跳转")
        self.state.node = target.id
        self.state.mission = target.mission

    def refresh_publication(self):
        self.pack.refresh_metadata()
        if self.pack.metadata.get('live_revision') or '_astralogue_live_revision' in self.state.variables:
            self.state.variables['_astralogue_live_revision']=self.pack.metadata.get('live_revision',{}).get('number',0)
        if self.pack.metadata.get('live_revision'):
            for key,value in self.pack.metadata.get('mission_initial_variables',{}).get(self.state.mission,{}).items():
                self.state.variables.setdefault(key,deepcopy(value))

    def next(self, step_limit: int = 1000) -> Event:
        """Emit and consume one dialogue, or stop at a stable choice/end/block.

        After DialogueEvent, state points at the next unread node. ChoiceEvent
        does not consume anything until choose() succeeds. This is also the save
        contract used by all front ends.
        """
        self.refresh_publication()
        seen = set()
        for _ in range(step_limit):
            nid = self.state.node
            if nid is None: return BlockedEvent(None, "任务入口缺失", "missing_entry")
            marker = canonical(self.snapshot())
            if marker in seen: return BlockedEvent(nid, "自动控制流重复相同状态", "auto_loop")
            seen.add(marker)
            try:
                n = self.pack.node(nid)
                if n.mission != self.state.mission: raise ValueError("当前节点和任务不一致")
                if n.kind not in KINDS or n.kind == "unknown":
                    return BlockedEvent(nid, f"未支持的指令: {n.data.get('operation', n.kind)}", "unsupported_operation")
                if n.kind == "end":
                    if self.pack.edges(nid): raise ValueError("结束节点包含冲突的跳转")
                    return EndEvent(nid)
                if n.kind == "dialogue":
                    text = self.pack.text(n.text, self.lang)
                    speaker = self.pack.text(n.speaker, self.lang, "未标注角色")
                    edge = self._single(nid)
                    self._move(edge)
                    return DialogueEvent(nid, speaker, text)
                if n.kind == "choice":
                    all_edges = self.pack.edges(nid)
                    if not all_edges or any(e.kind != "option" or e.value is None for e in all_edges): raise ValueError("无效选项关系")
                    edges = self._eligible(all_edges)
                    if not edges: return BlockedEvent(nid, "没有满足条件的选项", "no_options")
                    options = tuple(Option(e.value, self.pack.text(e.text, self.lang), e.target) for e in edges)
                    if len({o.value for o in options}) != len(options): raise ValueError("选项标识重复")
                    return ChoiceEvent(nid, options)
                if n.kind == "branch":
                    all_edges = self.pack.edges(nid)
                    if any(e.kind != "condition" or e.condition is None for e in all_edges): raise ValueError("条件分支缺少表达式")
                    edges = self._eligible(all_edges)
                    if len(edges) != 1: return BlockedEvent(nid, f"条件分支命中 {len(edges)} 个目标", "ambiguous_condition")
                    self._move(edges[0]); continue
                if n.kind == "call":
                    edges = self.pack.edges(nid)
                    calls, continuations = [e for e in edges if e.kind == "call"], [e for e in edges if e.kind == "next"]
                    if len(edges) != 2 or len(calls) != 1 or len(continuations) != 1 or any(e.condition is not None for e in edges):
                        raise ValueError("call 需要唯一 call 边和返回地址 next 边")
                    continuation = self.pack.node(continuations[0].target)
                    if continuation.mission != self.state.mission: raise ValueError("调用的返回地址必须属于调用者")
                    target = self.pack.node(calls[0].target)
                    if len(self.state.frames) >= 128: return BlockedEvent(nid, "调用栈超过上限 128", "call_depth")
                    self.state.frames.append({"call": nid, "mission": self.state.mission, "return": continuation.id})
                    self._move(calls[0], True); continue
                if n.kind == "return":
                    if not self.state.frames: raise ValueError("return 缺少调用上下文")
                    frame = self.state.frames[-1]
                    returns = [e for e in self.pack.edges(nid) if e.kind == "return" and e.target == frame["return"] and e.condition is None]
                    if len(returns) != 1: raise ValueError("返回地址没有显式 return 边")
                    if self.pack.node(frame["return"]).mission != frame["mission"]: raise ValueError("返回任务上下文无效")
                    self._move(returns[0], True); self.state.frames.pop(); continue
                # Resolve flow before mutating state, so a failed advance can
                # never repeatedly apply a variable assignment or emit.
                edge = self._single(nid)
                if n.kind == "set":
                    name = n.data.get("var")
                    if not isinstance(name, str) or "value" not in n.data: raise ValueError("无效变量赋值")
                    val = n.data["value"]
                    op = n.data.get("op", "set")
                    if op == "add":
                        old = self.state.variables.get(name)
                        if type(old) not in {int, float} or type(val) not in {int, float}: raise ValueError("add 需要已定义的数值变量")
                        val = old + val
                    elif op != "set": raise ValueError(f"未知变量操作: {op}")
                    self.state.variables[name] = deepcopy(val)
                elif n.kind == "emit":
                    event = n.data.get("event")
                    if not isinstance(event, str): raise ValueError("事件名缺失")
                    self.signal(event)
                elif n.kind == "wait":
                    event = n.data.get("event")
                    if event not in self.state.events: return BlockedEvent(nid, f"等待事件: {event}", "waiting_event")
                    if n.data.get("consume", False): self.state.events.remove(event)
                elif n.kind == "enter": self.state.context.append(self.state.mission)
                elif n.kind == "exit":
                    target = self.pack.node(edge.target)
                    if not self.state.context or self.state.context[-1] != target.mission: raise ValueError("任务退出上下文不匹配")
                    self.state.context.pop()
                self._move(edge, n.kind in {"enter", "exit"})
                if n.kind == "noop" and n.data.get("reason"):
                    return DiagnosticEvent(nid, "presentation_omitted", str(n.data["reason"]))
            except (ValueError, ConditionError, KeyError, TypeError) as ex:
                return BlockedEvent(nid, str(ex), "invalid_execution")
        return BlockedEvent(self.state.node, f"超过自动执行步数上限 {step_limit}", "step_limit")

    def choose(self, value: str) -> None:
        self.refresh_publication()
        nid = self.state.node
        if nid is None or self.pack.node(nid).kind != "choice": raise ValueError("当前没有玩家选项")
        edges = [e for e in self._eligible(self.pack.edges(nid)) if e.kind == "option" and e.value == value]
        if len(edges) != 1: raise ValueError("不存在或不可用的选项")
        edge = edges[0]
        target = self.pack.node(edge.target)
        if target.mission != self.state.mission: raise ValueError("选项不能直接跨任务")
        # Verify text before accepting a choice, including programmatic clients.
        self.pack.text(edge.text, self.lang)
        checkpoint = self.snapshot()
        self.history.append(checkpoint)
        self.state.choices.append({"node": nid, "edge": edge.id, "value": value})
        event = self.pack.node(nid).data.get("option_events", {}).get(value)
        if isinstance(event, str): self.signal(event)
        self._move(edge)

    def back(self) -> None:
        if not self.history: raise ValueError("没有可回溯的选择")
        self.state = State(**self.history.pop())

    def signal(self, event: str) -> None:
        if not event: raise ValueError("事件名不能为空")
        if event not in self.state.events: self.state.events.append(event)
        self.state.events.sort()

    def save(self, path: Path) -> None:
        if path.resolve() == self.pack.path.resolve(): raise ValueError("存档不能覆盖 StoryPack")
        obj = {"save_schema": 1, "pack_id": self.pack.metadata["pack_id"],
               "pack_version": self.pack.metadata["pack_version"], "pack_schema": self.pack.metadata["schema_version"],
               "language": self.lang, "state": self.snapshot(), "history": self.history}
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temp_path = Path(f.name)
            f.write(canonical(obj) + "\n")
        try: temp_path.replace(path)
        finally: temp_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, pack: StoryPack, path: Path) -> Runtime:
        if path.stat().st_size > 50 * 1024 * 1024: raise ValueError("存档过大")
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("save_schema") != 1: raise ValueError("不支持的存档版本")
        if (obj.get("pack_id"), obj.get("pack_version"), obj.get("pack_schema")) != (pack.metadata["pack_id"], pack.metadata["pack_version"], pack.metadata["schema_version"]):
            raise ValueError("存档与当前 StoryPack 不兼容，需要显式迁移")
        if not isinstance(obj.get("language"), str) or not isinstance(obj.get("history"), list): raise ValueError("存档字段不完整")
        states = [obj.get("state"), *obj["history"]]
        for state in states:
            if not isinstance(state, dict): raise ValueError("存档状态无效")
            try: parsed = State(**deepcopy(state))
            except TypeError as ex: raise ValueError("存档状态字段无效") from ex
            pack.mission(parsed.mission)
            if parsed.node is None or pack.node(parsed.node).mission != parsed.mission: raise ValueError("存档节点与任务不匹配")
            if not isinstance(parsed.variables, dict) or not isinstance(parsed.events, list) or not all(isinstance(x, str) for x in parsed.events): raise ValueError("存档变量或事件无效")
            if not isinstance(parsed.choices, list) or not isinstance(parsed.context, list): raise ValueError("存档执行上下文无效")
            if not isinstance(parsed.frames, list) or len(parsed.frames) > 128: raise ValueError("存档调用栈无效")
            for frame in parsed.frames:
                if not isinstance(frame, dict) or set(frame) != {"call", "mission", "return"} or not all(isinstance(v, str) for v in frame.values()): raise ValueError("存档调用帧无效")
                call = pack.node(frame["call"])
                if call.kind != "call" or call.mission != frame["mission"] or not any(e.kind == "next" and e.target == frame["return"] for e in pack.edges(call.id)):
                    raise ValueError("存档返回地址不属于调用节点")
                if pack.node(frame["return"]).mission != frame["mission"]: raise ValueError("存档返回任务无效")
            for mid in parsed.context: pack.mission(mid)
            for choice in parsed.choices:
                if not isinstance(choice, dict) or not any(e.id == choice.get("edge") and e.value == choice.get("value") for e in pack.edges(choice.get("node", ""))): raise ValueError("存档选择记录无效")
        rt = cls(pack, obj["state"]["mission"], obj["language"])
        rt.state = State(**deepcopy(obj["state"]))
        rt.history = deepcopy(obj["history"])
        return rt
