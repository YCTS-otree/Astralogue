"""Community Patch Protocol v1: bounded, evidence-bound Reader overlays."""
from copy import deepcopy
from dataclasses import asdict

from astralogue.conditions import check
from astralogue.model import Bundle, Edge, Node, digest


def validate_patch(bundle: Bundle, patch: dict) -> dict:
    if not isinstance(patch, dict): return {"valid": False, "errors": ["补丁必须为 JSON 对象"]}
    errors = []
    info = bundle.metadata.get("narrative", {})
    nodes = {n.id: n for n in bundle.nodes}
    edges = {e.id: e for e in bundle.edges}
    try:
        if patch.get("patch_version") != 1: raise ValueError("patch_version 必须为 1")
        if not isinstance(patch.get("id"), str) or not patch["id"].strip(): raise ValueError("缺少 patch id")
        if patch["id"] in info.get("patches", {}): raise ValueError("补丁已应用；请从基础 IR 重新构建")
        if patch.get("status") not in {"pending", "reviewed"}: raise ValueError("无效审核状态")
        if not info.get("game") or patch.get("game") != info["game"]: raise ValueError("游戏标识冲突")
        if patch.get("game_version") != info.get("game_version"): raise ValueError("游戏版本冲突")
        if not info.get("source_hashes") or patch.get("source_hashes") != info["source_hashes"]: raise ValueError("上游资源哈希变化或未绑定全部来源")
        evidence = patch.get("evidence")
        if not isinstance(evidence, list) or not evidence: raise ValueError("缺少来源证据")
        ids = [e.get("id") for e in evidence if isinstance(e, dict) and isinstance(e.get("uri"), str) and e["uri"].strip()]
        if len(ids) != len(evidence) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids): raise ValueError("无效或重复证据 ID/URI")
        if patch["status"] == "reviewed":
            review = patch.get("review", {})
            if not all(isinstance(review.get(k), str) and review[k].strip() for k in ["reviewer", "reviewed_at"]): raise ValueError("已审核补丁缺少审核人/日期")
            if not review.get("evidence") or set(review["evidence"]) - set(ids): raise ValueError("审核证据引用失效")
        operations = patch.get("operations")
        if not isinstance(operations, list) or not operations: raise ValueError("补丁没有操作")
        touched = set()
        adjacency = {}
        for edge in edges.values(): adjacency.setdefault(edge.source, set()).add(edge.target)
        for op in operations:
            if isinstance(op,dict) and op.get('op')=='text_parameter':
                node=nodes.get(op.get('source'))
                if node is None or info.get('modes',{}).get(node.mission,{}).get('mode')!='reader':raise ValueError('文本参数只能标注 Reader 节点')
                if patch['status']!='reviewed':raise ValueError('文本参数必须经审核')
                if op.get('parameter')!='nickname' or not isinstance(op.get('evidence'),list) or not op['evidence'] or set(op['evidence'])-set(ids):raise ValueError('文本参数/证据无效')
                if node.kind=='dialogue':key=node.text
                elif node.kind=='choice':
                    options=[e for e in bundle.edges if e.source==node.id and e.value==op.get('option')]
                    if len(options)!=1:raise ValueError('文本参数选项不唯一')
                    key=options[0].text
                else:raise ValueError('节点没有可标注文本')
                text=bundle.texts.get(key,{}).get(op.get('language','CHS'))
                start,end=op.get('start'),op.get('end')
                if not isinstance(text,str) or digest(text)!=op.get('text_hash') or type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or text[start:end]!=op.get('literal'):raise ValueError('文本参数范围或哈希已失效')
                annotations=node.data.get('text_parameters',[])
                if any(max(start,a['start'])<min(end,a['end']) for a in annotations):raise ValueError('文本参数范围冲突')
                if node.id in touched:raise ValueError('补丁节点重复操作')
                touched.add(node.id);continue
            if not isinstance(op, dict) or op.get("op") not in {"connect", "order", "condition", "event"}: raise ValueError("未知补丁操作")
            allowed = {"op", "source", "target", "mission", "evidence", "condition", "replace_edge", "event", "description"}
            if set(op) - allowed: raise ValueError("未知操作字段")
            source, target = op.get("source"), op.get("target")
            if source not in nodes or target not in nodes: raise ValueError("不存在的节点")
            if source in touched: raise ValueError("同一补丁对源节点存在冲突操作")
            touched.add(source)
            mission = op.get("mission")
            if nodes[source].mission != mission or nodes[target].mission != mission: raise ValueError("跨任务或任务归属冲突")
            if info.get("modes", {}).get(mission, {}).get("mode") != "reader": raise ValueError("补丁只能作用于 Reader，Strict 证据不可修改")
            if not isinstance(op.get("evidence"), list) or not op["evidence"] or set(op["evidence"]) - set(ids): raise ValueError("操作证据引用失效")
            if op.get("op") == "condition" and "condition" not in op: raise ValueError("条件操作缺少条件")
            if "condition" in op:
                check(op["condition"])
                known = set(bundle.metadata.get("initial_variables", {})) | set(bundle.metadata.get("mission_initial_variables", {}).get(mission, {}))
                known |= {n.data["var"] for n in nodes.values() if n.mission == mission and n.kind == "set" and isinstance(n.data.get("var"), str)}
                def check_variables(expr):
                    if isinstance(expr, dict):
                        if set(expr) == {"var"} and expr["var"] not in known: raise ValueError("补丁条件引用未定义变量")
                        for value in expr.values(): check_variables(value)
                    elif isinstance(expr, list):
                        for value in expr: check_variables(value)
                check_variables(op["condition"])
            if op["op"] == "event" and (not isinstance(op.get("event"), str) or not op["event"].strip()): raise ValueError("事件名缺失")
            outgoing = [e for e in edges.values() if e.source == source]
            # Even Reader copies retain protected original evidence. A community
            # status assertion is never sufficient to override that evidence.
            if any(info.get("relations", {}).get(e.id, {}).get("verified") for e in outgoing): raise ValueError("禁止覆盖已验证原始控制/结构关系")
            replacement = op.get("replace_edge")
            if outgoing:
                if len(outgoing) != 1 or replacement != outgoing[0].id: raise ValueError("现有关系冲突；必须明确替换唯一未验证策略边")
                adjacency[source].discard(outgoing[0].target)
            elif replacement: raise ValueError("失效的替换边引用")
            if nodes[source].kind not in {"unknown", "dialogue", "choice", "noop"}: raise ValueError("源节点不支持安全补丁")
            seen, pending = set(), [target]
            while pending:
                at = pending.pop()
                if at == source: raise ValueError("补丁引入循环")
                if at not in seen:
                    seen.add(at); pending.extend(adjacency.get(at, set()))
            adjacency.setdefault(source, set()).add(target)
    except (ValueError, TypeError, KeyError) as ex:
        errors.append(str(ex))
    return {"valid": not errors, "errors": errors, "status": patch.get("status"),
            "review_is_external_assertion": True, "strict_relations_modified": 0}


def apply_patch(bundle: Bundle, patch: dict, include_pending: bool = False) -> Bundle:
    result = validate_patch(bundle, patch)
    if not result["valid"]: raise ValueError("; ".join(result["errors"]))
    if patch["status"] == "pending" and not include_pending: raise ValueError("待审核补丁默认不应用；需显式 --include-pending")
    b = Bundle.from_dict(deepcopy(bundle.to_dict()))
    info = b.metadata["narrative"]
    original, original_edges, original_policies = {}, [], {}
    for i, op in enumerate(patch["operations"]):
        node = next(n for n in b.nodes if n.id == op["source"])
        original[node.id] = asdict(node)
        if op['op']=='text_parameter':
            node.data.setdefault('text_parameters',[]).append({k:deepcopy(op[k]) for k in ['start','end','literal','parameter','evidence']})
            node.data['text_parameters'][-1].update(patch=patch['id'],language=op.get('language','CHS'),option=op.get('option'))
            continue
        if node.id in info["policies"]: original_policies[node.id] = deepcopy(info["policies"][node.id])
        if op.get("replace_edge"):
            removed = next(e for e in b.edges if e.id == op["replace_edge"])
            original_edges.append({"edge": asdict(removed), "relation": info["relations"].pop(removed.id, {})})
            b.edges = [e for e in b.edges if e.id != op["replace_edge"]]
        gateway = "patch:" + digest([patch["id"], i])[:24]
        # Keep dialogue text intact; place consent after it. Unknown/empty
        # policy boundary can itself become the explicit consent menu.
        if node.kind == "dialogue":
            b.nodes.append(Node(gateway, node.mission, "choice"))
            b.edges.append(Edge(gateway + ":gate", node.id, gateway))
        else:
            gateway = node.id
            node.kind = "choice"
        gate = next(n for n in b.nodes if n.id == gateway)
        gate.data.update(reader_action="community_patch", reader_message=f"非官方补丁 {patch['id']} [{patch['status']}]：{op.get('description', op['op'])}")
        text = b.text(gateway + ":patch-label", gate.data["reader_message"] + "；确认采用修订")
        target = op["target"]
        if op["op"] == "event":
            event = gateway + ":event"
            b.nodes.append(Node(event, node.mission, "emit", data={"event": op["event"]}))
            b.edges.append(Edge(event + ":next", event, target))
            target = event
        eid = gateway + ":patch-edge"
        b.edges.append(Edge(eid, gateway, target, "option", text, op.get("condition"), "confirm"))
        provenance = {"origin": "community_reviewed" if patch["status"] == "reviewed" else "inferred",
                      "verified": False, "patch": patch["id"], "evidence": op["evidence"], "policy": "community_patch"}
        for edge in b.edges:
            if edge.id.startswith(gateway + ":") and edge.id not in info["relations"]: info["relations"][edge.id] = deepcopy(provenance)
        info["policies"][gateway] = {"action": "community_patch", "official": False, "patch": patch["id"], "status": patch["status"]}
    info.setdefault("patches", {})[patch["id"]] = {"document": deepcopy(patch), "sha256": digest(patch),
        "original_reader_nodes": original, "original_reader_edges": original_edges, "original_reader_policies": original_policies}
    return b
