"""Generic memory-write hook integration for Phi Memory."""

from __future__ import annotations

from typing import Any

from . import core


def on_pre_memory_write(**kwargs: Any) -> dict | None:
    if not core.phi_enabled():
        return None
    if kwargs.get("action") != "add":
        return None
    target = str(kwargs.get("target") or "memory")
    content = str(kwargs.get("content") or "")
    entries = list(kwargs.get("entries") or [])
    stage = str(kwargs.get("stage") or "before_add")
    store = kwargs.get("store")

    if stage == "before_add":
        candidate = core.score_text(
            content,
            target=target,
            explicit_user_request="remember" in content.lower(),
            existing_entries=entries,
        )
        if candidate.is_secret_or_sensitive:
            phi_info = candidate.to_dict()
            phi_info["text"] = "[REDACTED: sensitive memory candidate]"
            return {
                "action": "reject",
                "response": {
                    "success": False,
                    "error": "Phi Memory rejected this entry because it appears secret or sensitive.",
                    "phi": phi_info,
                },
            }
        normalized_content = core.normalize_text(content)
        if any(core.normalize_text(e) == normalized_content for e in entries):
            return {"action": "skip", "message": "Entry already exists (no duplicate added)."}
        return None

    if stage == "over_limit" and store is not None:
        cfg = core.phi_config()
        if not bool(cfg.get("auto_safe_cleanup_on_write_pressure")):
            return None
        limit = int(kwargs.get("limit") or 0)
        current = int(kwargs.get("current_chars") or 0)
        threshold = float(cfg.get("auto_safe_cleanup_threshold", 0.95) or 0.95)
        if limit <= 0 or (current / limit) < threshold:
            return None
        report = core.apply_safe_cleanup(store, target=target, already_locked=True)
        return {
            "action": "retry",
            "response_metadata": {
                "phi": {
                    "safe_cleanup_attempted": True,
                    "safe_cleanup": {
                        "success": report.get("success"),
                        "applied": report.get("applied"),
                        "entries_removed": report.get("entries_removed", 0),
                        "entries_redacted": report.get("entries_redacted", 0),
                        "old_chars": report.get("old_chars"),
                        "new_chars": report.get("new_chars"),
                        "percent_before": report.get("percent_before"),
                        "percent_after": report.get("percent_after"),
                        "backup_path": report.get("backup_path"),
                        "error": report.get("error"),
                    },
                },
            },
        }
    return None
