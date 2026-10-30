"""Third-party IR is supplementary evidence, never an implicit control override."""
from dataclasses import asdict

from astralogue.model import Bundle, Diagnostic, digest


def supplement_texts(primary: Bundle, overlay: Bundle, name: str) -> None:
    source = lambda b: b.metadata.get("source", {})
    primary_source, overlay_source = source(primary), source(overlay)
    trusted_version = primary_source.get("revision") not in {None, "unknown"} and primary_source.get("revision") == overlay_source.get("revision") and primary_source.get("game_version") == overlay_source.get("game_version")
    primary.metadata.setdefault("supplemental_evidence", []).append({"name": name, "hash": digest(overlay.to_dict()), "metadata": overlay.metadata,
                                                                  "control_imported": False, "same_game_version": trusted_version})
    conflicts = primary.metadata.setdefault("source_conflicts", [])
    texts = [("hsr:text:" + k.removeprefix("export:text:") if k.startswith("export:text:") and overlay.metadata.get("adapter") == "browser-sqlite" else k, v)
             for k, v in overlay.texts.items()]
    # JSONL lacks text hashes; only an explicit original sentence ID may link a
    # candidate to the primary text index. It never provides execution edges.
    index = primary.metadata.get("hsr_text_index", {})
    for node in overlay.nodes:
        original = index.get(str(node.data.get("sentence_id")), {})
        if original.get("text") and node.text in overlay.texts: texts.append((original["text"], overlay.texts[node.text]))
    candidates = primary.metadata.setdefault("supplemental_text_candidates", [])
    for key, languages in texts:
        for lang, text in languages.items():
            candidates.append({"source": name, "key": key, "language": lang, "value": text, "verified_revision": trusted_version})
            current = primary.texts.get(key, {}).get(lang)
            if current is not None and current != text:
                conflicts.append({"kind": "text", "key": key, "language": lang, "primary": current, "candidate": text, "source": name})
                affected = {e.source for e in primary.edges if e.text == key}
                affected.update(m.entry for m in primary.missions if m.title == key or primary.chapters.get(m.chapter) == key)
                for node in primary.nodes:
                    if node.id in affected or key in {node.text, node.speaker}:
                        primary.diagnostics.append(Diagnostic("source_text_conflict", f"文本来源冲突: {key}/{lang}", "error", node.mission, node.id))
                        original = asdict(node)
                        node.kind = "unknown"; node.data = {"operation": "source_text_conflict", "original_node": original}
            elif current is None and trusted_version and key.startswith("hsr:text:"):
                primary.text(key, text, lang)
                primary.source_refs.append({"file": name, "text": key, "language": lang, "source": "supplemental", "candidate": text})
    primary.source_refs.extend({"overlay": name, "untrusted_control": True, **ref} for ref in overlay.source_refs)
    if not trusted_version:
        primary.diagnostics.append(Diagnostic("unverified_supplement_version", f"{name}: 版本不明/不同，保留证据但不填入执行文本", "warning"))
