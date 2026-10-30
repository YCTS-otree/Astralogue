"""Conservative graph validation; structural termination is not a playability proof."""
from collections import Counter, defaultdict, deque
from dataclasses import asdict

from astralogue.conditions import ConditionError, check
from astralogue.model import Bundle, Diagnostic, KINDS, canonical


def validate(bundle: Bundle, lang: str = "CHS") -> dict:
    ds = list(bundle.diagnostics)

    def add(code, message, severity="error", mission=None, node=None):
        ds.append(Diagnostic(code, message, severity, mission, node))

    for label, objects in [("node", bundle.nodes), ("edge", bundle.edges), ("mission", bundle.missions)]:
        for key, count in Counter(x.id for x in objects).items():
            if count > 1: add("duplicate_id", f"{label}: {key} 重复 {count} 次")
    nodes = {n.id: n for n in bundle.nodes}
    missions = {m.id: m for m in bundle.missions}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for n in nodes.values():
        if n.mission not in missions: add("missing_mission", n.mission, node=n.id)
        if n.kind not in KINDS: add("unknown_type", n.kind, mission=n.mission, node=n.id)
        if n.kind == "unknown": add("unsupported_operation", "未知或未证明安全的指令", mission=n.mission, node=n.id)
        for key in [n.text, n.speaker]:
            if key is not None and lang not in bundle.texts.get(key, {}):
                add("missing_text", f"{key}/{lang}", mission=n.mission, node=n.id)
        if n.kind == "dialogue" and n.text is None:
            add("missing_text", "台词节点没有文本引用", mission=n.mission, node=n.id)
        if n.kind == "set" and (not isinstance(n.data.get("var"), str) or "value" not in n.data):
            add("invalid_set", "变量名或值缺失", mission=n.mission, node=n.id)
        if n.kind == "set" and n.data.get("op", "set") not in {"set", "add"}:
            add("invalid_set", "未知变量操作", mission=n.mission, node=n.id)
        if n.kind in {"wait", "emit"} and not isinstance(n.data.get("event"), str):
            add("invalid_event", "事件名缺失", mission=n.mission, node=n.id)
    for e in bundle.edges:
        outgoing[e.source].append(e)
        incoming[e.target].append(e.source)
        n = nodes.get(e.source)
        mid = n.mission if n else None
        if n is None or e.target not in nodes: add("missing_target", f"{e.source} → {e.target}", mission=mid, node=e.source)
        if e.kind not in {"next", "option", "condition"}: add("unknown_edge", e.kind, mission=mid, node=e.source)
        if n and e.target in nodes and nodes[e.target].mission != mid and n.kind not in {"enter", "exit"}:
            add("cross_mission_edge", "跨任务跳转需要 enter/exit 节点", mission=mid, node=e.source)
        if e.text is not None and lang not in bundle.texts.get(e.text, {}):
            add("missing_text", f"{e.text}/{lang}", mission=mid, node=e.source)
        if e.condition is not None:
            try: check(e.condition)
            except ConditionError as ex: add("invalid_condition", str(ex), mission=mid, node=e.source)
        if e.kind == "condition" and e.condition is None:
            add("invalid_condition", "条件边缺少表达式", mission=mid, node=e.source)
        if e.kind == "option" and (e.text is None or e.value is None):
            add("invalid_option", "选项缺少文本或选择标识", mission=mid, node=e.source)
    for n in nodes.values():
        edges = outgoing[n.id]
        if n.kind == "choice":
            if not edges or any(e.kind != "option" for e in edges):
                add("invalid_choice", "选项节点需要 option 边", mission=n.mission, node=n.id)
            if len({e.value for e in edges}) != len(edges):
                add("duplicate_option", "选择标识重复", mission=n.mission, node=n.id)
        elif n.kind == "branch":
            if not edges or any(e.condition is None for e in edges):
                add("invalid_branch", "条件节点需要显式条件边", mission=n.mission, node=n.id)
            elif all(isinstance(e.condition, bool) for e in edges):
                if sum(e.condition for e in edges) != 1:
                    add("ambiguous_condition", "常量条件没有唯一命中", mission=n.mission, node=n.id)
            elif not (len(edges) == 2 and (canonical(edges[0].condition) == canonical({"not": edges[1].condition}) or canonical(edges[1].condition) == canonical({"not": edges[0].condition}))):
                add("conditional_coverage", "无法证明分支条件互斥且覆盖所有状态", "warning", n.mission, n.id)
        elif n.kind == "end":
            if edges: add("end_has_edges", "结束节点包含跳转", mission=n.mission, node=n.id)
        elif n.kind != "unknown" and (len(edges) != 1 or edges[0].kind != "next" or edges[0].condition is not None):
            add("ambiguous_flow", "需要唯一的无条件 next 边", mission=n.mission, node=n.id)
        if n.kind == "wait" and n.data.get("internal"):
            producers = [e for e in bundle.edges if e.target == n.id and e.source in nodes]
            if not producers or any(not ((nodes[e.source].kind == "emit" and nodes[e.source].data.get("event") == n.data.get("event")) or
                (nodes[e.source].kind == "choice" and nodes[e.source].data.get("option_events", {}).get(e.value) == n.data.get("event"))) for e in producers):
                add("unproven_wait", "无法证明所有入边都提供所需事件", "warning", n.mission, n.id)
    # Reverse reachability finds nodes with no structural route to an explicit end.
    terminating = {n.id for n in nodes.values() if n.kind == "end"}
    queue = deque(sorted(terminating))
    while queue:
        for prev in incoming[queue.popleft()]:
            if prev not in terminating:
                terminating.add(prev); queue.append(prev)
    reach_by_mission = {}
    for m in bundle.missions:
        if lang not in bundle.texts.get(m.title, {}): add("missing_title", m.title, mission=m.id)
        if m.chapter not in bundle.chapters: add("missing_chapter", m.chapter, mission=m.id)
        elif lang not in bundle.texts.get(bundle.chapters[m.chapter], {}): add("missing_chapter_text", m.chapter, mission=m.id)
        if m.entry not in nodes or nodes[m.entry].mission != m.id:
            add("missing_entry", "任务入口缺失或属于其他任务", mission=m.id)
        reachable = set()
        queue = deque([m.entry] if m.entry in nodes else [])
        while queue:
            nid = queue.popleft()
            if nid in reachable: continue
            reachable.add(nid)
            queue.extend(e.target for e in outgoing[nid] if e.target in nodes)
        reach_by_mission[m.id] = reachable
        initial = set(bundle.metadata.get("initial_variables", {}))
        definitions = {n.data.get("var") for n in nodes.values() if n.kind == "set" and isinstance(n.data.get("var"), str)}
        definite = {nid: (set(initial) if nid == m.entry else initial | definitions) for nid in reachable}

        def after(nid):
            assigned = set(definite[nid])
            n = nodes[nid]
            if n.kind == "set" and isinstance(n.data.get("var"), str): assigned.add(n.data["var"])
            return assigned

        changed = True
        while changed:
            changed = False
            for nid in sorted(reachable):
                if nid == m.entry: continue
                preds = [p for p in incoming[nid] if p in reachable]
                assigned = set.intersection(*(after(p) for p in preds)) if preds else set(initial)
                if assigned != definite[nid]: definite[nid] = assigned; changed = True

        def references(obj):
            if isinstance(obj, dict):
                if set(obj) == {"var"} and isinstance(obj["var"], str): return {obj["var"]}
                return set().union(*(references(x) for x in obj.values()))
            if isinstance(obj, list): return set().union(*(references(x) for x in obj))
            return set()

        for nid in sorted(reachable):
            for e in outgoing[nid]:
                missing = references(e.condition) - after(nid)
                if missing: add("undefined_variable", "条件变量并非在所有入路径上已赋值: " + ",".join(sorted(missing)), mission=nodes[nid].mission, node=nid)
            n = nodes[nid]
            if n.kind == "set" and n.data.get("op") == "add" and n.data.get("var") not in definite[nid]:
                add("undefined_variable", "add 之前变量未可靠初始化", mission=n.mission, node=nid)
        # Find cycles even if they also have exits; variable termination is not proven.
        colors = {}
        for start in sorted(reachable):
            if colors.get(start): continue
            colors[start] = 1
            stack = [(start, iter(e.target for e in outgoing[start] if e.target in reachable))]
            while stack:
                current, targets = stack[-1]
                target = next(targets, None)
                if target is None:
                    colors[current] = 2; stack.pop(); continue
                if colors.get(target) == 1:
                    add("possible_cycle", f"可能不终止的环: {current} → {target}", "warning", m.id, current)
                elif not colors.get(target):
                    colors[target] = 1
                    stack.append((target, iter(e.target for e in outgoing[target] if e.target in reachable)))
        for n in nodes.values():
            if n.mission != m.id: continue
            if n.id not in reachable: add("unreachable", "节点无法从本任务入口到达", "warning", m.id, n.id)
            elif n.id not in terminating: add("no_end_path", "没有到达显式结束的结构路径", "warning", m.id, n.id)
    statuses = {}
    global_errors = any(d.severity == "error" and d.mission is None for d in ds)
    for m in bundle.missions:
        md = [d for d in ds if d.mission == m.id]
        errors = [d for d in md if d.severity == "error"]
        reachable = reach_by_mission[m.id]
        # Cosmetic setup must not hide a blocker before the first usable story
        # event (e.g. Initialize -> missing Timeline is still BLOCKED).
        cursor, prefix_seen, prefix_blocked = m.entry, set(), False
        while cursor in nodes and cursor not in prefix_seen:
            prefix_seen.add(cursor)
            n = nodes[cursor]
            if n.kind == "unknown" or n.kind not in KINDS or any(d.node == cursor for d in errors):
                prefix_blocked = True; break
            if n.kind in {"dialogue", "choice", "end", "branch", "wait"}: break
            es = outgoing[cursor]
            if len(es) != 1: break
            cursor = es[0].target
        if global_errors or prefix_blocked or any(d.node is None or d.node == m.entry for d in errors): status = "BLOCKED"
        elif errors or any(d.severity == "warning" for d in md): status = "PARTIAL"
        elif any(nodes[x].kind == "wait" and not nodes[x].data.get("internal") for x in reachable if x in nodes): status = "PARTIAL"
        else: status = "RESOLVED"
        statuses[m.id] = status
    return {"language": lang, "missions": statuses, "counts": {"missions": len(missions), "nodes": len(nodes), "edges": len(bundle.edges),
            "diagnostics": len(ds), **dict(Counter(statuses.values()))}, "diagnostics": [asdict(d) for d in ds],
            "scope": "静态图检查；RESOLVED 不代表原游戏完整任务或所有状态组合已验证"}
