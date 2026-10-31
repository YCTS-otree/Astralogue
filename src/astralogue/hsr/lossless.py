"""Validate native object identity against independently exported SerializedFile bytes."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from astralogue.model import load_json, file_hash
from .native_timeline import mono_header


def _bundle_fields(data: bytes) -> dict:
    """Independently verify the observed Windows NamedObject/AssetBundle layout."""
    pos = 0
    def read(fmt):
        nonlocal pos
        size = struct.calcsize("<" + fmt)
        if pos + size > len(data): raise ValueError("Truncated AssetBundle field")
        values = struct.unpack_from("<" + fmt, data, pos); pos += size
        return values[0] if len(values) == 1 else values
    def count():
        value = read("i")
        if not 0 <= value <= 100000: raise ValueError("Invalid AssetBundle count")
        return value
    def text():
        nonlocal pos
        length = count()
        if pos + length > len(data): raise ValueError("Truncated AssetBundle string")
        value = data[pos:pos+length].decode("utf-8"); pos = (pos+length+3) & ~3
        return value
    def pointer():
        file, path = read("iq")
        return {"m_FileID": file, "m_PathID": path}
    name = text()
    preload = [pointer() for _ in range(count())]
    containers = []
    for _ in range(count()):
        containers.append({"name": text(), "preloadIndex": read("i"), "preloadSize": read("i"), "asset": pointer()})
    return {"name": name, "preload": preload, "containers": containers}


def validate_export(manifest: Path) -> dict:
    m = load_json(manifest)
    if m.get("format") != "astralogue-lossless-v1": raise ValueError("Unknown lossless format")
    base = manifest.parent.resolve()
    serialized = base / "serialized-file.dat"
    if file_hash(serialized) != m["serialized_file_id"]: raise ValueError("SerializedFile hash mismatch")
    data = serialized.read_bytes()
    if len(data) != m["serialized_file_bytes"]: raise ValueError("SerializedFile size mismatch")
    if len(m["objects"]) != m["object_count"]: raise ValueError("Object count mismatch")
    ids, headers, ranges = {}, {}, []
    for obj in m["objects"]:
        pid = obj["path_id"]
        if not isinstance(pid, int) or pid in ids: raise ValueError("Duplicate or invalid PathID")
        path = (base / obj["raw"]).resolve()
        if path.parent != base or path.suffix != ".dat": raise ValueError("Object path escape")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != obj["sha256"]: raise ValueError("Object hash mismatch")
        start, size = obj["byte_start"], obj["byte_size"]
        if start < 0 or size != len(raw) or start + size > len(data) or data[start:start + size] != raw:
            raise ValueError("Object differs from original SerializedFile range")
        ids[pid] = obj; ranges.append((start, start + size))
        if obj.get("asset_bundle"):
            actual = _bundle_fields(raw)
            if actual.pop("name") != obj["name"] or actual != obj["asset_bundle"]:
                raise ValueError("AssetBundle references differ from original bytes")
            if any(c["preloadIndex"] < 0 or c["preloadSize"] < 0 or
                   c["preloadIndex"] + c["preloadSize"] > len(actual["preload"])
                   for c in actual["containers"]):
                raise ValueError("AssetBundle preload range invalid")
        if obj["type"] == "MonoBehaviour": headers[pid] = mono_header(path)
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])): raise ValueError("Overlapping object ranges")
    resolved, unresolved = [], []
    for pid, header in headers.items():
        for field in ("m_GameObject", "m_Script"):
            ref = header[field]
            if not ref["m_PathID"]: continue
            evidence = {"owner": pid, "field": field, "reference": ref}
            if ref["m_FileID"] == 0 and ref["m_PathID"] in ids: resolved.append(evidence)
            else: unresolved.append(evidence)
    bundle_resolved, bundle_unresolved = [], []
    for obj in m["objects"]:
        bundle = obj.get("asset_bundle")
        if not bundle: continue
        for ref in bundle["preload"] + [c["asset"] for c in bundle["containers"]]:
            if not ref["m_PathID"]: continue
            evidence = {"owner": obj["path_id"], "reference": ref}
            if ref["m_FileID"] == 0 and ref["m_PathID"] in ids: bundle_resolved.append(evidence)
            else: bundle_unresolved.append(evidence)
    return {"manifest": str(manifest), "serialized_file_id": m["serialized_file_id"],
            "objects_verified": len(ids), "serialized_file_verified": True,
            "known_references_resolved": resolved, "known_references_unresolved": unresolved,
            "bundle_references_resolved": bundle_resolved, "bundle_references_unresolved": bundle_unresolved,
            "reference_scope": "MonoBehaviour base and AssetBundle PPtrs; custom references require native decoder",
            "opaque_control_payloads": len(headers), "manifest_data": m}
