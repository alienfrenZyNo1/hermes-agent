"""Generic memory-write hook integration for Phi Memory."""

from __future__ import annotations

import json
from typing import Any

from . import core, semantic


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
        limit = int(kwargs.get("limit") or 0)
        current = int(kwargs.get("current_chars") or 0)
        if limit <= 0:
            return None

        safe_enabled = bool(cfg.get("auto_safe_cleanup_on_write_pressure"))
        semantic_enabled = bool(cfg.get("auto_semantic_compression_on_write_pressure"))
        if not safe_enabled and not semantic_enabled:
            return None

        metadata: dict[str, Any] = {"phi": {}}
        pressure_ratio = current / limit

        if safe_enabled:
            safe_threshold = float(cfg.get("auto_safe_cleanup_threshold", 0.95) or 0.95)
            if pressure_ratio >= safe_threshold:
                safe_report = core.apply_safe_cleanup(store, target=target, already_locked=True)
                metadata["phi"].update({
                    "safe_cleanup_attempted": True,
                    "safe_cleanup": {
                        "success": safe_report.get("success"),
                        "applied": safe_report.get("applied"),
                        "entries_removed": safe_report.get("entries_removed", 0),
                        "entries_redacted": safe_report.get("entries_redacted", 0),
                        "old_chars": safe_report.get("old_chars"),
                        "new_chars": safe_report.get("new_chars"),
                        "percent_before": safe_report.get("percent_before"),
                        "percent_after": safe_report.get("percent_after"),
                        "backup_path": safe_report.get("backup_path"),
                        "error": safe_report.get("error"),
                    },
                })
                current = int(safe_report.get("new_chars") or store._char_count(target))
                pressure_ratio = current / limit

        if semantic_enabled:
            targets = cfg.get("auto_semantic_compression_targets", ["memory"])
            if isinstance(targets, str):
                try:
                    parsed_targets = json.loads(targets)
                except json.JSONDecodeError:
                    parsed_targets = targets
                targets = parsed_targets
            if isinstance(targets, str):
                targets = [part.strip() for part in targets.split(",") if part.strip()]
            semantic_threshold = float(cfg.get("auto_semantic_compression_threshold", cfg.get("auto_safe_cleanup_threshold", 0.95)) or 0.95)
            min_savings = int(cfg.get("auto_semantic_compression_min_savings_chars", 200) or 0)
            if target in set(targets) and pressure_ratio >= semantic_threshold:
                delimiter_chars = len("\n§\n") if store._entries_for(target) else 0
                budget = max(0, limit - len(content.strip()) - delimiter_chars)
                proposal = semantic.semantic_compression_proposal(store, target=target, budget=budget)
                savings = int(proposal.get("old_chars") or 0) - int(proposal.get("proposed_chars") or 0)
                if savings >= min_savings:
                    semantic_report = semantic.apply_semantic_compression(
                        store,
                        target=target,
                        budget=budget,
                        already_locked=True,
                        reason="auto_write_pressure",
                    )
                else:
                    semantic_report = dict(proposal)
                    semantic_report.update({
                        "applied": False,
                        "policy_warning": f"Skipped semantic compression because projected savings {savings} chars are below configured minimum {min_savings}.",
                    })
                metadata["phi"].update({
                    "semantic_compression_attempted": True,
                    "semantic_compression": {
                        "success": semantic_report.get("success"),
                        "applied": semantic_report.get("applied"),
                        "entries_removed": semantic_report.get("entries_removed", 0),
                        "old_chars": semantic_report.get("old_chars"),
                        "proposed_chars": semantic_report.get("proposed_chars"),
                        "backup_path": semantic_report.get("backup_path"),
                        "error": semantic_report.get("error"),
                        "policy_warning": semantic_report.get("policy_warning"),
                    },
                })

        if metadata["phi"]:
            return {"action": "retry", "response_metadata": metadata}
    return None
