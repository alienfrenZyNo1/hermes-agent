"""Fibonacci review scheduling for Phi Memory."""

from __future__ import annotations

from typing import Any

from . import core, metadata


def _intervals() -> list[int]:
    cfg = core.phi_config()
    raw = cfg.get("fibonacci_review_intervals") or core.FIBONACCI_REVIEW_INTERVALS
    return [int(x) for x in raw] or [1, 2, 3, 5, 8, 13]


def _suggest_action(entry: dict[str, Any], text: str) -> str:
    if entry.get("skill_candidate") or core.classify_memory_type(text, entry.get("target", "memory")) == core.MemoryType.SKILL_CANDIDATE.value:
        return "convert_to_skill_candidate"
    score = float(entry.get("last_phi_score", 0) or 0)
    if score >= core.PHI_MAJOR:
        return "promote"
    if int(entry.get("review_count", 0) or 0) >= 2 and int(entry.get("access_count", 0) or 0) == 0:
        return "archive"
    if score < 0.42:
        return "compress"
    return "keep"


def review_due(store: Any, target: str = "memory", interactions: int | None = None) -> dict[str, Any]:
    payload = metadata.load_sidecar(store, target)
    texts_by_id = {metadata.memory_id(target, text): text for text in store._entries_for(target)}
    due = []
    for mid, entry in payload.get("entries", {}).items():
        threshold = int(entry.get("next_review_after_interactions", 1) or 1)
        observed = int(entry.get("access_count", 0) or 0) if interactions is None else int(interactions)
        if observed >= threshold:
            text = texts_by_id.get(mid, entry.get("safe_preview", ""))
            due.append({
                "memory_id": mid,
                "safe_preview": entry.get("safe_preview", ""),
                "why_due": f"observed {observed} interaction(s), threshold {threshold}",
                "current_score": float(entry.get("last_phi_score", 0) or 0),
                "suggested_action": _suggest_action(entry, text),
                "next_review_interval_if_kept": _intervals()[min(int(entry.get("review_interval_index", 0) or 0) + 1, len(_intervals()) - 1)],
            })
    return {"success": True, "target": target, "due": due, "count": len(due)}


def mark_reviewed(store: Any, target: str, memory_id: str, useful: bool = True, contradicted: bool = False) -> dict[str, Any]:
    payload = metadata.load_sidecar(store, target)
    entry = payload.get("entries", {}).get(memory_id)
    if not entry:
        return {"success": False, "error": f"Unknown memory_id: {memory_id}"}
    intervals = _intervals()
    idx = int(entry.get("review_interval_index", 0) or 0)
    if useful and not contradicted:
        idx = min(idx + 1, len(intervals) - 1)
        entry["stability_score"] = min(1.0, float(entry.get("stability_score", 0) or 0) + 0.1)
        entry["confidence_score"] = min(1.0, float(entry.get("confidence_score", 0) or 0) + 0.1)
        entry["last_action"] = "keep"
    elif contradicted:
        entry["last_action"] = "supersede"
    else:
        entry["last_action"] = "compress"
    entry["review_count"] = int(entry.get("review_count", 0) or 0) + 1
    entry["review_interval_index"] = idx
    entry["next_review_after_interactions"] = intervals[idx]
    entry["updated_at"] = metadata.now_iso()
    payload["updated_at"] = metadata.now_iso()
    metadata._atomic_write_json(metadata.sidecar_path(store, target), payload)
    return {"success": True, "memory_id": memory_id, "entry": entry}


def schedule(store: Any, target: str = "memory") -> dict[str, Any]:
    payload = metadata.load_sidecar(store, target)
    items = []
    for mid, entry in payload.get("entries", {}).items():
        items.append({
            "memory_id": mid,
            "safe_preview": entry.get("safe_preview", ""),
            "review_interval_index": entry.get("review_interval_index", 0),
            "next_review_after_interactions": entry.get("next_review_after_interactions", 1),
            "review_count": entry.get("review_count", 0),
            "access_count": entry.get("access_count", 0),
        })
    return {"success": True, "target": target, "schedule": items, "count": len(items)}
