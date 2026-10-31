"""Compile an explicitly evidenced logical-time schedule to ordinary Story IR.

No wall-clock sleeps and no game objects exist in the runtime. A wait holds the
logical clock until an explicit event; simultaneous effects require ordering
evidence and otherwise block. Native adapters cannot invent resume events.
"""
from dataclasses import dataclass, field
import math

from astralogue.model import Bundle, Node, Edge


@dataclass
class ScheduledAction:
    id: str
    start: float
    kind: str
    data: dict = field(default_factory=dict)
    text: str | None = None
    speaker: str | None = None
    after: tuple[str, ...] = ()


def compile_schedule(bundle: Bundle, mission: str, prefix: str, actions: list[ScheduledAction],
                     end_time: float, *, end_verified: bool, blockers: list[dict] | None = None) -> tuple[str, str | None]:
    if not math.isfinite(end_time) or end_time < 0: raise ValueError("Invalid schedule end")
    if len({a.id for a in actions}) != len(actions): raise ValueError("Duplicate schedule action")
    if any(not math.isfinite(a.start) or a.start < 0 or a.start > end_time for a in actions):
        raise ValueError("Action outside schedule bounds")
    entry = prefix + ":clock:entry"
    clock = "schedule:" + prefix + ":time"
    bundle.metadata.setdefault("logical_clocks", {})[prefix] = clock
    bundle.nodes.append(Node(entry, mission, "set", data={"var": clock, "value": 0.0}))
    previous = entry
    def node(nid, kind, data=None, text=None, speaker=None):
        nonlocal previous
        bundle.nodes.append(Node(nid, mission, kind, text, speaker, data or {}))
        bundle.edges.append(Edge(nid+":incoming", previous, nid)); previous = nid
    if blockers:
        node(prefix+":preflight", "unknown", {"operation": "NativeTimelinePreflight", "blockers": blockers})
        return entry, None
    completed = set()
    for timestamp in sorted({a.start for a in actions}):
        group = [a for a in actions if a.start == timestamp]
        node(prefix+":clock:"+str(timestamp), "set", {"var": clock, "value": timestamp})
        while group:
            ready = [a for a in group if set(a.after) <= completed]
            if len(ready) != 1:
                node(prefix+":ambiguous:"+str(timestamp), "unknown",
                     {"operation": "AmbiguousParallelSchedule", "time": timestamp, "actions": [a.id for a in group]})
                return entry, None
            action = ready[0]; group.remove(action)
            if action.kind not in {"dialogue", "wait", "emit", "set", "noop"}:
                node(prefix+":action:"+action.id, "unknown", {"operation": action.kind, **action.data})
                return entry, None
            if action.kind in {"wait", "emit"} and (not isinstance(action.data.get("event"), str) or not action.data["event"]):
                node(prefix+":action:"+action.id, "unknown", {"operation": "UnverifiedEventBinding"})
                return entry, None
            node(prefix+":action:"+action.id, action.kind, action.data, action.text, action.speaker)
            completed.add(action.id)
    node(prefix+":clock:end", "set", {"var": clock, "value": end_time})
    if not end_verified:
        node(prefix+":end:unknown", "unknown", {"operation": "UnverifiedTimelineEndPolicy"})
        return entry, None
    nid = prefix+":return"
    node(nid, "return")
    return entry, nid
