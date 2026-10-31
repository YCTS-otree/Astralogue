"""Native Unity objects: validated headers, opaque payloads and reference graph.

This decoder deliberately does not assign story semantics to unknown clip payloads.
The header layout is the observed Unity 64-bit-pathID, little-endian layout.
"""
from __future__ import annotations

import struct
from pathlib import Path

from astralogue.model import file_hash

BASE_FIELDS = {"m_GameObject", "m_Enabled", "m_Script", "m_Name"}


def mono_header(path: Path) -> dict:
    if path.suffix.lower() != ".dat": raise ValueError("Expected Raw .dat export")
    data = path.read_bytes()
    if len(data) < 32: raise ValueError("Truncated MonoBehaviour header")
    game_file, game_path, enabled, script_file, script_path, length = struct.unpack_from("<iqiiqi", data)
    if enabled not in (0, 1) or length < 0 or length > len(data) - 32:
        raise ValueError("Not the supported MonoBehaviour header layout")
    try: name = data[32:32 + length].decode("utf-8")
    except UnicodeError as ex: raise ValueError("Invalid MonoBehaviour name") from ex
    end = (32 + length + 3) & ~3
    if end > len(data): raise ValueError("Truncated name alignment")
    if game_file < 0 or script_file < 0: raise ValueError("Invalid PPtr file index")
    return {"sha256": file_hash(path), "layout": "unity-le-pathid64-monobehaviour",
            "m_GameObject": {"m_FileID": game_file, "m_PathID": game_path},
            "m_Enabled": enabled, "m_Script": {"m_FileID": script_file, "m_PathID": script_path},
            "m_Name": name, "payload_offset": end, "payload_bytes": len(data) - end,
            "payload_hex": data[end:].hex(), "control_semantics": "UNKNOWN"}


def reference_graph(objects: list[dict]) -> dict:
    """Link only scoped Unity PPtrs; tracks and clips never imply execution edges.

    Each input object needs file identity and pathID. External file tables must be
    supplied separately before nonzero fileID references can be linked.
    """
    index, conflicts, links, missing = {}, [], [], []
    for record in objects:
        key = (record["file"], record["path_id"])
        if key in index: conflicts.append(list(key))
        index[key] = record
    def walk(value, owner):
        if isinstance(value, dict):
            if isinstance(value.get("m_PathID"), int) and value["m_PathID"]:
                target = (owner["file"], value["m_PathID"])
                edge = {"from": [owner["file"], owner["path_id"]], "reference": value}
                if value.get("m_FileID") == 0 and target in index and list(target) not in conflicts:
                    links.append({**edge, "to": list(target)})
                else: missing.append(edge)
            for child in value.values(): walk(child, owner)
        elif isinstance(value, list):
            for child in value: walk(child, owner)
    for record in objects: walk(record["raw"], record)
    return {"object_count": len(objects), "links": links, "unresolved": missing,
            "conflicts": conflicts, "execution_edges": [], "ir_converted": False}
