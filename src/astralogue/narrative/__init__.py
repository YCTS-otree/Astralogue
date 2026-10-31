"""Evidence-preserving Reader projections; no game or UI dependencies."""
from __future__ import annotations

from copy import deepcopy
from astralogue.model import Bundle, Diagnostic, Edge, Mission, Node, digest

ORIGINS = {"original_control", "native_structure", "inferred", "community_reviewed", "unknown"}


class Reconstruction:
    """Append a separately scoped reading graph without rewriting Strict evidence."""

    def __init__(self, strict: Bundle, mission: str, title: str, entry: str):
        self.bundle = Bundle.from_dict(deepcopy(strict.to_dict()))
        self.mission = mission
        self.bundle.text(mission + ":title", title)
        self.bundle.missions.append(Mission(mission, mission + ":title", entry))
        self.bundle.metadata.setdefault("narrative", {"version": 1, "relations": {}, "policies": {}, "modes": {}})
        self.info = self.bundle.metadata["narrative"]
        self.info["modes"][mission] = {"mode": "reader", "scope": "reading_segment", "strict_complete": False}
        self.info.setdefault("strict_fingerprint", digest(strict.to_dict()))
        self.bundle.diagnostics.append(Diagnostic("reader_projection", "文字阅读投影；用户确认不证明原游戏调度或完整任务完成", "warning", mission))

    def node(self, nid: str, kind: str, **data) -> str:
        self.bundle.nodes.append(Node(nid, self.mission, kind, data=data))
        return nid

    def edge(self, source: str, target: str, origin="unknown", evidence=None, policy=None, **kwargs) -> str:
        if origin not in ORIGINS: raise ValueError("未知证据类别")
        if origin in {"inferred", "community_reviewed", "unknown"} and policy is None:
            raise ValueError("未验证关系必须显式声明文字体验策略")
        eid = source + ":edge:" + digest([target, kwargs])[:20]
        self.bundle.edges.append(Edge(eid, source, target, **kwargs))
        self.info["relations"][eid] = {"origin": origin, "verified": origin in {"original_control", "native_structure"} and policy is None,
                                        "evidence_verified": origin in {"original_control", "native_structure"},
                                        "evidence": evidence or {}, "policy": policy}
        return eid

    def confirm(self, nid: str, target: str, message: str, evidence=None, action="confirmation") -> str:
        self.node(nid, "choice", reader_action=action, reader_message=message)
        key = self.bundle.text(nid + ":confirm", message + "；确认继续（Reader 策略）")
        self.info["policies"][nid] = {"action": action, "message": message, "evidence": evidence or {}, "official": False}
        self.edge(nid, target, evidence=evidence, policy=action, kind="option", text=key, value="confirm")
        return nid

    def guide(self, nid: str, targets: dict[str, str], evidence=None) -> str:
        """No default route: the reader explicitly chooses a nonofficial link."""
        self.node(nid, "choice", reader_action="manual_guide", reader_message="后续关系未知；以下均为非官方人工引导")
        self.info["policies"][nid] = {"action": "manual_guide", "official": False, "evidence": evidence or {}}
        for target, label in targets.items():
            text = self.bundle.text(nid + ":" + digest(target)[:16], "非官方引导：" + label)
            self.edge(nid, target, policy="manual_guide", kind="option", text=text, value=target)
        return nid

    def unordered(self, nid: str, actions: list[tuple[str, str, str]], target: str) -> str:
        """Explicit user ordering for simultaneous actions; never sort their IDs."""
        # tuples: entry, exit, label. Each is visited exactly once.
        variables = self.bundle.metadata.setdefault("mission_initial_variables", {}).setdefault(self.mission, {})
        names = [nid + ":visited:" + str(i) for i in range(len(actions))]
        for name in names: variables[name] = False
        self.node(nid, "branch")
        complete = {"all": [{"eq": [{"var": name}, True]} for name in names]}
        menu = nid + ":order"
        self.edge(nid, target, policy="user_order", kind="condition", condition=complete)
        self.edge(nid, menu, policy="user_order", kind="condition", condition={"not": complete})
        self.node(menu, "choice", reader_action="user_order", reader_message="同刻内容没有已知先后关系；请选择人工阅读顺序")
        self.info["policies"][menu] = {"action": "user_order", "official": False}
        for i, (entry, exit_, label) in enumerate(actions):
            key = self.bundle.text(menu + f":{i}", "人工排序：" + label)
            self.edge(menu, entry, policy="user_order", kind="option", value=str(i), text=key,
                      condition={"eq": [{"var": names[i]}, False]})
            mark = menu + f":mark:{i}"
            self.node(mark, "set", var=names[i], value=True)
            self.edge(exit_, mark, policy="user_order")
            self.edge(mark, nid, policy="user_order")
        return nid


def audit(pack, save: dict) -> dict:
    """Reconstruct an audit from pack-bound save choices, including confirmations."""
    if save.get("pack_id") != pack.metadata["pack_id"]: raise ValueError("存档与剧情包不兼容")
    info = pack.metadata.get("narrative", {})
    records = []
    for choice in save["state"]["choices"]:
        node = pack.node(choice["node"])
        edge = next((e for e in pack.edges(node.id) if e.id == choice["edge"] and e.value == choice["value"]), None)
        if edge is None: raise ValueError("存档选择引用失效")
        records.append({**choice, "target": edge.target, "action": node.data.get("reader_action", "original_choice"),
                        "evidence": info.get("relations", {}).get(edge.id, {}),
                        "policy": info.get("policies", {}).get(node.id)})
    mission = save["state"]["mission"]
    mode = info.get("modes", {}).get(mission, {"mode": "strict"})
    current = pack.node(save["state"]["node"]) if save["state"]["node"] else None
    return {"pack_id": save["pack_id"], "mission": mission, **mode, "records": records,
            "reading_end_reached": bool(current and current.kind == "end" and mode["mode"] == "reader"),
            "original_game_completion_proven": False}
