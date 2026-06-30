"""Text/JSON memory health dashboard for Phi Memory."""

from __future__ import annotations

from typing import Any

from . import core, metadata, review, skills


def _duplicate_counts(entries: list[str]) -> dict[str, int]:
    exact = len(entries) - len(set(entries))
    normalized = len(entries) - len({core.normalize_text(e) for e in entries})
    return {"exact": max(0, exact), "normalized": max(0, normalized)}


def dashboard(store: Any, target: str | None = None) -> dict[str, Any]:
    targets = [target] if target in {"memory", "user"} else ["memory", "user"]
    items = []
    for tgt in targets:
        entries = store._entries_for(tgt)
        rendered = "\n§\n".join(entries)
        limit = store._char_limit(tgt)
        scores = [(e, core.score_text(e, target=tgt).phi_score) for e in entries]
        sidecar = metadata.sidecar_status(store, tgt)
        due = review.review_due(store, tgt)
        skill_candidates = skills.find_skill_candidates(store, tgt)
        sensitive = sum(1 for e in entries if core.sensitivity_score_for_text(e)[1])
        large = sorted(entries, key=len, reverse=True)[:5]
        low = sorted(scores, key=lambda item: item[1])[:5]
        recommendations = []
        pressure = core.pressure_level(len(rendered), limit)
        if pressure["level"] in {"review", "consolidate", "emergency"}:
            recommendations.append("Run semantic compression proposal to reduce memory pressure.")
        if skill_candidates["count"]:
            recommendations.append("Consider moving procedural memory into a draft skill.")
        if due["count"]:
            recommendations.append("Review due memories and mark reviewed after inspection.")
        if not recommendations:
            recommendations.append("No immediate action required.")
        items.append({
            "target": tgt,
            "chars": {"used": len(rendered), "limit": limit},
            "pressure": pressure,
            "long_short_split": {"long_term": round(core.PHI_MAJOR, 4), "short_term": round(core.PHI_MINOR, 4)},
            "entries": len(entries),
            "duplicates": _duplicate_counts(entries),
            "sensitive_redaction_candidates": sensitive,
            "stale_entries": 0,
            "review_due_entries": due["count"],
            "skill_candidates": skill_candidates["count"],
            "semantic_compression_opportunities": max(_duplicate_counts(entries)["normalized"], pressure["level"] != "healthy"),
            "top_large_entries": [metadata.safe_preview(e) for e in large],
            "top_low_score_entries": [{"score": round(s, 3), "safe_preview": metadata.safe_preview(e)} for e, s in low],
            "last_safe_cleanup_date": None,
            "last_review_date": None,
            "sidecar": {"status": sidecar["status"], "path": sidecar["path"]},
            "recommended_actions": recommendations,
        })
    if target in {"memory", "user"}:
        return {"success": True, **items[0]}
    return {"success": True, "targets": items}


def format_dashboard(data: dict[str, Any]) -> str:
    if "targets" in data:
        return "\n\n".join(format_dashboard({"success": True, **item}) for item in data["targets"])
    lines = [
        "Phi Memory Dashboard",
        f"Target: {data.get('target')}",
        f"Pressure: {data.get('pressure', {}).get('level')} {data.get('pressure', {}).get('percent')}%",
        f"Chars: {data.get('chars', {}).get('used')} / {data.get('chars', {}).get('limit')}",
        f"Entries: {data.get('entries')}",
        f"Sidecar: {data.get('sidecar', {}).get('status')}",
        f"Due reviews: {data.get('review_due_entries')}",
        f"Skill candidates: {data.get('skill_candidates')}",
        f"Duplicates: {data.get('duplicates', {}).get('normalized')}",
        f"Sensitive candidates: {data.get('sensitive_redaction_candidates')}",
        "Recommended action:",
    ]
    lines.extend(f"- {item}" for item in data.get("recommended_actions", []))
    return "\n".join(lines)
