"""Proposal-only semantic compression for Phi Memory."""

from __future__ import annotations

import difflib
from typing import Any

from tools.memory_tool import ENTRY_DELIMITER

from . import core


def _is_low_value(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("debug note", "random thing", "noisy", "truncated", "todo maybe"))


def _preserve_exact(text: str) -> bool:
    lowered = text.lower()
    return bool(
        any(k in lowered for k in ("repo", "path", "database", "db", "app", "deploy", "command", "decision", "risk", "open loop"))
        or any(ch in text for ch in ("/", "\\"))
    )


def _semantic_entries(entries: list[str], budget: int | None = None) -> list[str]:
    seen = set()
    proposed = []
    for entry in entries:
        clean = core._sanitize_for_diff(entry.strip())
        if not clean:
            continue
        norm = core.normalize_text(clean)
        if norm in seen:
            continue
        seen.add(norm)
        if _is_low_value(clean):
            continue
        proposed.append(clean)
    if budget and len(ENTRY_DELIMITER.join(proposed)) > budget:
        # Deterministic proposal-only pruning: prefer high Phi score entries. Do
        # not mutate; exact project/operational facts are retained even if that
        # means the proposal cannot fully satisfy an aggressive budget.
        protected = [item for item in proposed if _preserve_exact(item)]
        protected_ids = {id(item) for item in protected}
        scored = sorted([item for item in proposed if id(item) not in protected_ids], key=lambda t: core.score_text(t).phi_score, reverse=True)
        kept = list(protected)
        for item in scored:
            candidate = kept + [item]
            if len(ENTRY_DELIMITER.join(candidate)) <= budget or not kept:
                kept.append(item)
        proposed = kept
    return proposed


def semantic_compression_proposal(store: Any, target: str = "memory", budget: int | None = None) -> dict[str, Any]:
    if not bool(core.phi_config().get("semantic_compression_enabled", True)):
        return {"success": False, "error": "Semantic compression proposals are disabled by phi_memory.semantic_compression_enabled=false."}
    entries = store._entries_for(target)
    old_text = ENTRY_DELIMITER.join(core._sanitize_for_diff(e) for e in entries)
    proposed_entries = _semantic_entries(entries, budget=budget)
    proposed_text = ENTRY_DELIMITER.join(proposed_entries)
    diff = "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        proposed_text.splitlines(keepends=True),
        fromfile=f"{target.upper()}.md before",
        tofile=f"{target.upper()}.md semantic proposal",
    ))
    limit = store._char_limit(target)
    return {
        "success": True,
        "target": target,
        "semantic": True,
        "applied": False,
        "budget": budget,
        "old_chars": len(old_text),
        "proposed_chars": len(proposed_text),
        "pressure_before": core.pressure_level(len(old_text), limit),
        "projected_pressure_after": core.pressure_level(len(proposed_text), limit),
        "proposed_text": proposed_text,
        "diff": diff,
        "note": "Proposal only. No memory files were changed.",
    }


def format_semantic_proposal(report: dict[str, Any]) -> str:
    if not report.get("success"):
        return report.get("error", "Semantic proposal failed.")
    lines = [
        f"Phi Memory semantic compression proposal ({report.get('target', 'memory')})",
        "Applied: false (proposal only)",
        f"Chars: {report.get('old_chars')} → {report.get('proposed_chars')}",
        f"Pressure: {report.get('pressure_before', {}).get('percent')}% → {report.get('projected_pressure_after', {}).get('percent')}%",
        "",
        "Diff:",
        report.get("diff", ""),
    ]
    return "\n".join(lines).strip()
