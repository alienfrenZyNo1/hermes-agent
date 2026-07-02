"""Semantic compression for Phi Memory.

Semantic compression is proposal-only by default.  Applying it is an
explicitly gated, advanced opt-in because it can remove low-value unique
entries rather than only performing deterministic duplicate/secret cleanup.
"""

from __future__ import annotations

import difflib
import shutil
from datetime import datetime, timezone
from pathlib import Path
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


def _semantic_report(
    store: Any,
    target: str = "memory",
    budget: int | None = None,
    *,
    applied: bool = False,
    backup_path: str = "",
    note: str = "Proposal only. No memory files were changed.",
) -> dict[str, Any]:
    entries = store._entries_for(target)
    old_text_raw = ENTRY_DELIMITER.join(entries)
    old_text = ENTRY_DELIMITER.join(core._sanitize_for_diff(e) for e in entries)
    proposed_entries = _semantic_entries(entries, budget=budget)
    proposed_text_raw = ENTRY_DELIMITER.join(proposed_entries)
    proposed_text = ENTRY_DELIMITER.join(core._sanitize_for_diff(e) for e in proposed_entries)
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
        "applied": applied,
        "budget": budget,
        "old_chars": len(old_text_raw),
        "proposed_chars": len(proposed_text_raw),
        "entries_before": len(entries),
        "entries_after": len(proposed_entries),
        "entries_removed": max(0, len(entries) - len(proposed_entries)),
        "pressure_before": core.pressure_level(len(old_text_raw), limit),
        "projected_pressure_after": core.pressure_level(len(proposed_text_raw), limit),
        "proposed_text": proposed_text,
        "diff": diff,
        "backup_path": backup_path,
        "note": note,
    }


def semantic_compression_proposal(store: Any, target: str = "memory", budget: int | None = None) -> dict[str, Any]:
    if not bool(core.phi_config().get("semantic_compression_enabled", True)):
        return {"success": False, "error": "Semantic compression proposals are disabled by phi_memory.semantic_compression_enabled=false."}
    return _semantic_report(store, target=target, budget=budget)


def apply_semantic_compression(
    store: Any,
    target: str = "memory",
    budget: int | None = None,
    *,
    already_locked: bool = False,
    reason: str = "manual",
) -> dict[str, Any]:
    """Apply opt-in semantic compression with backup and diff.

    This is intentionally gated by ``phi_memory.semantic_compression_apply_enabled``.
    It uses the same deterministic semantic proposal algorithm as
    ``semantic_compression_proposal``; it does not call an LLM.
    """
    if target not in {"memory", "user"}:
        return {"success": False, "error": "Invalid --target for Phi Memory. Use --target memory or --target user."}
    cfg = core.phi_config()
    if not bool(cfg.get("semantic_compression_enabled", True)):
        return {"success": False, "error": "Semantic compression is disabled by phi_memory.semantic_compression_enabled=false."}
    if not bool(cfg.get("semantic_compression_apply_enabled", False)):
        return {"success": False, "error": "Semantic compression apply is disabled by phi_memory.semantic_compression_apply_enabled=false."}
    if not hasattr(store, "_path_for") or not hasattr(store, "_write_file"):
        return {"success": False, "error": "Memory store does not support semantic compression apply."}

    path: Path = store._path_for(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        entries = raw.split(ENTRY_DELIMITER) if raw.strip() else []
        store._set_entries(target, list(entries))
        proposed_entries = _semantic_entries(entries, budget=budget)
        if entries and not proposed_entries:
            return {"success": False, "error": "Refusing semantic compression because it would leave the memory file empty."}
        old_rendered = ENTRY_DELIMITER.join(entries)
        proposed_rendered = ENTRY_DELIMITER.join(proposed_entries)
        report = _semantic_report(store, target=target, budget=budget)
        if proposed_rendered == old_rendered:
            report["note"] = "No semantic compression changes were needed."
            return report

        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup = path.with_name(f"{path.name}.semantic.bak.{ts}")
        suffix = 0
        while backup.exists():
            suffix += 1
            backup = path.with_name(f"{path.name}.semantic.bak.{ts}.{suffix}")
        try:
            if path.exists():
                shutil.copy2(path, backup)
            else:
                backup.write_text("", encoding="utf-8")
        except (OSError, IOError) as exc:
            report.update({
                "success": False,
                "applied": False,
                "backup_path": str(backup),
                "error": f"Backup creation failed; memory file was not changed: {exc}",
                "note": "Semantic compression aborted before writing because backup creation failed.",
            })
            return report
        store._write_file(path, proposed_entries)
        store._set_entries(target, list(proposed_entries))
        report.update({
            "applied": True,
            "backup_path": str(backup),
            "note": f"Applied opt-in semantic compression ({reason}); backup created before writing.",
        })
        return report

    if already_locked:
        return _run()
    lock_fn = getattr(store, "_file_lock", None)
    if lock_fn is None:
        return _run()
    with lock_fn(path):
        return _run()


def format_semantic_proposal(report: dict[str, Any]) -> str:
    if not report.get("success"):
        return report.get("error", "Semantic proposal failed.")
    lines = [
        f"Phi Memory semantic compression proposal ({report.get('target', 'memory')})",
        f"Applied: {str(bool(report.get('applied'))).lower()}",
        f"Chars: {report.get('old_chars')} → {report.get('proposed_chars')}",
        f"Pressure: {report.get('pressure_before', {}).get('percent')}% → {report.get('projected_pressure_after', {}).get('percent')}%",
        f"Backup: {report.get('backup_path') or '—'}",
        "",
        "Diff:",
        report.get("diff", ""),
    ]
    return "\n".join(lines).strip()
