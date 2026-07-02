"""Model-facing phi_memory tool handler."""

from __future__ import annotations

from typing import Any

from tools.registry import tool_error, tool_result

from . import core, dashboard, metadata, review, semantic, session_recall, skills
from .memory_adapter import get_store


def handle_phi_memory(args: dict, **_kwargs: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    target = str(args.get("target") or "memory").strip().lower()
    if target not in {"memory", "user"} and action != "dashboard":
        return tool_error("Invalid target for Phi Memory. Use target='memory' or target='user'.")

    store = get_store()
    try:
        if action in {"status", "review"}:
            return tool_result(core.review_store(store, target=target, dry_run=True))
        if action == "dashboard":
            dash_target = target if target in {"memory", "user"} else None
            return tool_result(dashboard.dashboard(store, target=dash_target))
        if action == "meta_status":
            return tool_result(metadata.sidecar_status(store, target))
        if action == "meta_rebuild":
            return tool_result(metadata.rebuild_sidecar(store, target))
        if action == "meta_validate":
            return tool_result(metadata.validate_sidecar(store, target))
        if action == "review_due":
            return tool_result(review.review_due(store, target=target))
        if action == "schedule":
            return tool_result(review.schedule(store, target=target))
        if action == "compress":
            if bool(args.get("apply_safe")):
                return tool_result(core.apply_safe_cleanup(store, target=target))
            if bool(args.get("apply_semantic")):
                return tool_result(semantic.apply_semantic_compression(store, target=target, budget=args.get("budget")))
            if bool(args.get("semantic")):
                return tool_result(semantic.semantic_compression_proposal(store, target=target, budget=args.get("budget")))
            report = core.review_store(store, target=target, dry_run=True)
            report["mode"] = "compress"
            report["note"] = "Compression is currently proposal-only; no memory files were changed."
            return tool_result(report)
        if action == "explain":
            text = str(args.get("text") or "")
            return tool_result(core.explain_text(text, target=target, existing_entries=store._entries_for(target)))
        if action == "recall":
            text = str(args.get("text") or "")
            return tool_result(session_recall.recall_with_fallback(
                store,
                text,
                target=target,
                include_session=bool(args.get("include_session")),
                active_only=bool(args.get("active_only")),
            ))
        if action == "skill_candidates":
            return tool_result(skills.find_skill_candidates(store, target=target))
        return tool_error("Unknown phi_memory action.")
    except Exception as exc:
        return tool_error(f"phi_memory failed: {type(exc).__name__}: {exc}")
