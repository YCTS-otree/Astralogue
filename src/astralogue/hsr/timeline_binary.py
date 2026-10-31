"""Evidence-gated HSR 4.6 Timeline layouts, observed in DS104060102 samples.

Unity Timeline clip fields follow the public TimelineClip serialized field order.
Game-specific prefix/tail bytes remain opaque. Unsupported versions fail closed.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from .lossless import validate_export
from .native_timeline import mono_header


class Reader:
    def __init__(self, data: bytes, offset: int = 0): self.data, self.pos = data, offset
    def read(self, fmt: str):
        size = struct.calcsize("<" + fmt)
        if self.pos + size > len(self.data): raise ValueError("Truncated native field")
        value = struct.unpack_from("<" + fmt, self.data, self.pos); self.pos += size
        return value[0] if len(value) == 1 else value
    def count(self):
        count = self.read("i")
        if not 0 <= count <= 100000: raise ValueError("Invalid array count")
        return count
    def pptr(self):
        file, path = self.read("iq")
        if file < 0: raise ValueError("Invalid fileID")
        return {"m_FileID": file, "m_PathID": path}
    def string(self):
        length = self.count()
        if self.pos + length > len(self.data): raise ValueError("Truncated string")
        text = self.data[self.pos:self.pos+length].decode("utf-8")
        self.pos = (self.pos + length + 3) & ~3
        if self.pos > len(self.data): raise ValueError("Truncated alignment")
        return text
    def curve(self):
        count = self.count()
        end = self.pos + count * 28 + 12
        if end > len(self.data): raise ValueError("Truncated animation curve")
        self.pos = end


def clip(reader: Reader, *, preserve_nonfinite_aux: bool = False) -> dict:
    start_offset = reader.pos
    if reader.read("i") != 1: raise ValueError("Unsupported TimelineClip version")
    start, clip_in = reader.read("d"), reader.read("d")
    asset = reader.pptr()
    duration, scale = reader.read("d"), reader.read("d")
    parent = reader.pptr()
    ease_blend = [reader.read("d") for _ in range(4)]
    reader.curve(); reader.curve()
    blend_modes = [reader.read("i"), reader.read("i")]
    exposed = [reader.string() for _ in range(reader.count())]
    curves = reader.pptr()
    recordable = reader.read("i")
    post, pre = reader.read("i"), reader.read("i")
    post_time, pre_time = reader.read("d"), reader.read("d")
    display = reader.string()
    if not all(math.isfinite(n) for n in (start, clip_in, duration, scale)):
        raise ValueError("Nonfinite clip time")
    if not preserve_nonfinite_aux and not all(math.isfinite(n) for n in (*ease_blend, post_time, pre_time)):
        raise ValueError("Nonfinite clip time")
    if start < 0 or duration < 0 or scale <= 0 or recordable not in (0, 1): raise ValueError("Invalid clip time/flags")
    def auxiliary(value):
        return value if math.isfinite(value) else {"ieee754_le": struct.pack("<d", value).hex(), "semantic": "UNVERIFIED_NONFINITE_SENTINEL"}
    return {"byte_start": start_offset, "byte_end": reader.pos, "start": start, "clip_in": clip_in,
            "duration": duration, "time_scale": scale, "asset": asset, "parent": parent,
            "ease_blend": [auxiliary(v) for v in ease_blend], "blend_modes": blend_modes, "exposed_parameters": exposed,
            "animation_curves": curves, "recordable": recordable, "post_extrapolation": post,
            "pre_extrapolation": pre, "post_time": auxiliary(post_time), "pre_time": auxiliary(pre_time), "display_name": display}


def decode(manifest: Path, sentence_ids: set[int], *, track_profile: str = "m58") -> dict:
    if track_profile not in {"m58", "binding-v2"}: raise ValueError("Unknown native track profile")
    validated = validate_export(manifest); m = validated.pop("manifest_data")
    if m.get("unity_version", "").split("\n", 1)[0] != "2019.4.34f1":
        raise ValueError("Native layout not validated for this Unity version")
    objects = {obj["path_id"]: obj for obj in m["objects"]}
    decoded, errors = {}, []
    for pid, obj in objects.items():
        if obj["type"] != "MonoBehaviour": continue
        path = manifest.parent / obj["raw"]; header = mono_header(path); data = path.read_bytes()
        script_ref = header["m_Script"]
        if script_ref["m_FileID"] != 0 or script_ref["m_PathID"] not in objects: continue
        script = objects[script_ref["m_PathID"]].get("script") or {}
        cls = script.get("m_ClassName"); offset = header["payload_offset"]
        record = {"path_id": pid, "class": cls, "name": header["m_Name"], "sha256": obj["sha256"],
                  "script": script_ref, "script_type": script, "payload_offset": offset, "raw": obj["raw"],
                  "layout_status": "HEADER_ONLY"}
        try:
            if cls == "PlaySimpleTalkClip":
                if script.get("m_Namespace") != "RPGTools.Timeline" or script.get("m_AssemblyName") != "Assembly-CSharp.dll":
                    raise ValueError("Unverified PlaySimpleTalkClip script type")
                r = Reader(data, offset + 8); sid = r.read("I")
                if sid not in sentence_ids: raise ValueError("TalkSentenceID not found in source table")
                record.update(talk_sentence_id=sid, sentence_field_offset=offset+8,
                              layout_status="VERIFIED_SENTENCE_ID",
                              unknown_payload_hex=data[offset:offset+8].hex()+":"+data[offset+12:].hex())
            elif cls == "TimelineAsset":
                if script.get("m_Namespace") != "UnityEngine.Timeline": raise ValueError("Unknown TimelineAsset script type")
                r = Reader(data, offset)
                record["unknown_prefix"] = r.read("i")
                record["binding_data"] = r.pptr()
                record["tracks"] = [r.pptr() for _ in range(r.count())]
                record["fixed_duration"] = r.read("d")
                record["editor_float_candidate"] = r.read("f")
                record["duration_mode"] = r.read("i")
                record["marker_track"] = r.pptr()
                if r.pos != len(data): raise ValueError("Unknown TimelineAsset tail/layout")
                record["layout_status"] = "TIMELINE_REFERENCES"
            elif cls and cls.endswith("Track"):
                r = Reader(data, offset)
                if r.read("i") != 3: raise ValueError("Unsupported TrackAsset version")
                # Validated observed prefix; its undisclosed flags are NOT execution defaults.
                record["unknown_prefix_hex"] = data[offset+4:offset+64].hex()
                r.pos = offset + 64; record["parent"] = r.pptr()
                record["children"] = [r.pptr() for _ in range(r.count())]
                if track_profile == "binding-v2":
                    begin = r.pos
                    record["binding_name"] = r.string()
                    record["binding_transform_path"] = r.string()
                    record["unknown_preclips_hex"] = data[begin:r.pos].hex()
                else:
                    record["unknown_preclips_hex"] = data[r.pos:r.pos+8].hex(); r.pos += 8
                record["declared_clip_count"] = r.count()
                record["clips"] = [clip(r, preserve_nonfinite_aux=track_profile == "binding-v2") for _ in range(record["declared_clip_count"])]
                for c in record["clips"]:
                    if c["parent"] != {"m_FileID": 0, "m_PathID": pid}: raise ValueError("Clip parent mismatch")
                record["unknown_tail_hex"] = data[r.pos:].hex()
                record["layout_status"] = "TRACK_CLIP_FIELDS"
            if cls == "PauseMarkerClip":
                if len(data) != offset: raise ValueError("Unrecognized PauseMarkerClip payload")
                record.update(layout_status="EMPTY_MARKER_PAYLOAD", resume_condition=None)
            elif cls == "SimpleTalkMarkerClip":
                r = Reader(data, offset)
                if len(data)-offset != 28: raise ValueError("Unrecognized SimpleTalkMarkerClip layout")
                words = [r.read("I") for _ in range(7)]
                record.update(marker_words=words, marker_sentence_candidate=words[-1] if words[-1] in sentence_ids else None,
                              layout_status="MARKER_WORDS_UNVERIFIED_SEMANTICS")
            decoded[pid] = record
        except (ValueError, struct.error, UnicodeError) as ex:
            errors.append({"path_id": pid, "class": cls, "reason": str(ex)})
            if track_profile == "binding-v2":
                record.update(layout_status="PARTIAL_LAYOUT", parsing_error=str(ex))
                record.pop("clips", None)
                decoded[pid] = record
    links, unresolved = [], []
    for pid, record in decoded.items():
        def link(value, field):
            if isinstance(value, dict):
                if "m_PathID" in value and value["m_PathID"]:
                    edge = {"owner": pid, "field": field, "reference": value}
                    if value["m_FileID"] == 0 and value["m_PathID"] in objects: links.append(edge)
                    else: unresolved.append(edge)
                for key, child in value.items(): link(child, field+"/"+key)
            elif isinstance(value, list):
                for i, child in enumerate(value): link(child, field+"/"+str(i))
        link(record, "")
    return {"serialized_file_id": m["serialized_file_id"], "objects": list(decoded.values()),
            "errors": errors, "links": links, "unresolved": unresolved,
            "validation": validated, "track_profile": track_profile, "unknown_control_semantics": True}
