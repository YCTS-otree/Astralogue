"""Loss-aware import of observed third-party exports, without their code/schema coupling.

Exports do not prove original session entry or preserve arbitrary game controls.
They are useful staging material, but remain BLOCKED until enriched from raw data
or an explicitly authored IR. No top-level array adjacency is treated as flow.
"""
from pathlib import Path
from contextlib import closing
import json
import sqlite3

from astralogue.model import Bundle, Diagnostic, Edge, Mission, Node, file_hash, load_json


def load_extracted(path: Path, lang: str, kind: str) -> Bundle:
    b = Bundle(metadata={"adapter": kind, "languages": [lang], "inputs": {path.name: file_hash(path)}})
    b.text("default-title", "第三方提取会话", lang)
    if kind == "browser-sqlite":
        # Open strictly read-only; never execute upstream SQL or modify its DB.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            required = {"dialogue_group": {"group_id", "mission_id", "act_file", "sequence_index", "wait_custom_string"},
                        "dialogue_line": {"group_id", "sort_order", "talk_type", "talk_sentence_id", "text_hash", "name_hash", "option_group_index", "trigger_custom_string"},
                        "text_map": {"hash", "lang", "text"}}
            for table, columns in required.items():
                actual = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                if not columns <= actual: raise ValueError(f"未支持的第三方 SQLite Schema: {table}")
            textmap = {str(r["hash"]): r["text"] for r in con.execute("SELECT hash,text FROM text_map WHERE lang=?", (lang,))}
            groups = [dict(r) for r in con.execute("SELECT * FROM dialogue_group ORDER BY act_file,sequence_index,group_id")]
            records = []
            for g in groups:
                lines = [dict(r) for r in con.execute("SELECT * FROM dialogue_line WHERE group_id=? ORDER BY sort_order", (g["group_id"],))]
                # Preserve ordered group contents and all upstream columns as raw
                # material. They are not an executable transcript of predicates.
                records.append({"group": g, "lines": lines, "textmap": {h: textmap[h] for r in lines for h in [str(r["text_hash"]), str(r["name_hash"])] if h in textmap}})
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "group_triggers" in tables:
                b.metadata["group_triggers"] = [dict(r) for r in con.execute("SELECT * FROM group_triggers ORDER BY group_id,trigger")]
        # Grouped DB exports have already discarded non-dialogue instructions.
        for i, record in enumerate(records):
            mid = f"extracted:{path.stem}:group:{i}"
            title = b.text(mid + ":title", f"{record['group']['mission_id']} / {record['group']['act_file']} / {record['group']['sequence_index']}", lang)
            entry = mid + ":unresolved"
            b.missions.append(Mission(mid, title, entry, original_id=str(record["group"]["mission_id"])))
            b.nodes.append(Node(entry, mid, "unknown", data={"reason": "上游 SQLite 不保留完整控制指令，需要原始数据补全", "export": record}))
            b.source_refs.append({"file": path.name, "pointer": f"/dialogue_group/{record['group']['group_id']}", "node": entry, "raw": record})
            b.diagnostics.append(Diagnostic("lossy_sqlite", "已导入文本和触发关系原始记录；不可把浏览器排序视为剧情流", "error", mid, entry))
            for li, line in enumerate(record["lines"]):
                nid = f"{mid}:line:{li}"
                th, nh = str(line["text_hash"]), str(line["name_hash"])
                text, speaker = f"export:text:{th}", f"export:text:{nh}"
                if th in record["textmap"]: b.text(text, record["textmap"][th], lang)
                if nh in record["textmap"]: b.text(speaker, record["textmap"][nh], lang)
                else: speaker = None
                kind = "dialogue" if line["talk_type"] == "simple_talk" else "unknown"
                b.nodes.append(Node(nid, mid, kind, text, speaker, {"sentence_id": line["talk_sentence_id"], "export": line}))
                b.source_refs.append({"file": path.name, "pointer": f"/dialogue_group/{record['group']['group_id']}/line/{li}", "node": nid, "original_id": line["talk_sentence_id"], "raw": line})
        if not records: raise ValueError("第三方 SQLite 没有 dialogue_group 记录")
        return b
    if kind == "starrail-jsonl":
        records = []
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                if line.strip(): records.append(json.loads(line))
    else:
        obj = load_json(path)
        records = [obj] if isinstance(obj, list) else [obj]
    for ri, record in enumerate(records):
        mid = f"extracted:{path.stem}:{ri}"
        entry = mid + ":unresolved-entry"
        b.missions.append(Mission(mid, b.text(mid + ":title", f"{path.stem} / {ri}", lang), entry))
        b.nodes.append(Node(entry, mid, "unknown", data={"reason": "上游已丢失入口及部分控制指令"}))
        b.source_refs.append({"file": path.name, "pointer": f"/record/{ri}", "node": entry, "raw": record})
        b.diagnostics.append(Diagnostic("lossy_export", "显式 next_TalkSentenceID 已保留；未猜测会话入口及块间顺序", "error", mid, entry))
        blocks = record if isinstance(record, list) else []
        targets: dict[str, list[str]] = {}
        pending = []
        for bi, block in enumerate(blocks):
            if not isinstance(block, dict): continue
            nid = f"{mid}:b{bi}"
            typ = str(block.get("type", "")).rsplit(".", 1)[-1]
            if typ == "PlayAndWaitSimpleTalk":
                prev = None
                for ti, talk in enumerate(block.get("conversations", [])):
                    did = f"{nid}:l{ti}"
                    text = b.text(did + ":text", str(talk["content"]), lang) if "content" in talk else None
                    speaker = b.text(did + ":speaker", str(talk["role"]), lang) if "role" in talk else None
                    b.nodes.append(Node(did, mid, "dialogue", text, speaker, {"sentence_id": talk.get("TalkSentenceID")}))
                    if prev: b.edges.append(Edge(prev + ":next", prev, did))
                    targets.setdefault(str(talk.get("TalkSentenceID")), []).append(did)
                    prev = did
                if prev and "next_TalkSentenceID" in block: pending.append((prev, str(block["next_TalkSentenceID"]), "next", None, None))
            elif typ == "PlayOptionTalk":
                b.nodes.append(Node(nid, mid, "choice"))
                for oi, opt in enumerate(block.get("options", [])):
                    text = b.text(f"{nid}:option:{oi}", str(opt["content"]), lang) if "content" in opt else None
                    pending.append((nid, str(opt.get("next_TalkSentenceID")), "option", text, str(oi + 1)))
            elif typ == "EndPerformance": b.nodes.append(Node(nid, mid, "end"))
            else:
                b.nodes.append(Node(nid, mid, "unknown", data={"raw": block}))
                if "TalkSentenceID" in block: targets.setdefault(str(block["TalkSentenceID"]), []).append(nid)
                if "next_TalkSentenceID" in block: pending.append((nid, str(block["next_TalkSentenceID"]), "next", None, None))
        for i, (src, target, edge_kind, text, val) in enumerate(pending):
            candidates = targets.get(target, [])
            if len(candidates) == 1: b.edges.append(Edge(f"{mid}:e{i}", src, candidates[0], edge_kind, text, value=val))
            else: b.diagnostics.append(Diagnostic("unresolved_export_target", f"目标 {target} 对应 {len(candidates)} 个节点", "error", mid, src))
    if not records: raise ValueError("输入没有记录")
    return b
