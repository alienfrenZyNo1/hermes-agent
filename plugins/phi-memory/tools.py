"""Model-facing phi_memory tool handler."""

from __future__ import annotations

import json
from typing import Any

from tools.registry import tool_error, tool_result

from . import core
from .memory_adapter import get_store


def handle_phi_memory(args: dict, **_kwargs: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    target = str(args.get("target") or "memory").strip().lower()
    if target not in {"memory", "user"}:
        return tool_error("Invalid target for Phi Memory. Use target='memory' or target='user'.")

    store = get_store()
    try:
        if action in {"status", "review"}:
            return tool_result(core.review_store(store, target=target, dry_run=True))
        if action == "compress":
            if bool(args.get("apply_safe")):
                return tool_result(core.apply_safe_cleanup(store, target=target))
            report = core.review_store(store, target=target, dry_run=True)
            report["mode"] = "compress"
            report["note"] = "Compression is currently proposal-only; no memory files were changed."
            return tool_result(report)
        if action == "explain":
            text = str(args.get("text") or "")
            return tool_result(core.explain_text(text, target=target, existing_entries=store._entries_for(target)))
        if action == "recall":
            text = str(args.get("text") or "")
            return tool_result(core.recall(store, text, target=target))
        return tool_error("Unknown phi_memory action. Use status, review, compress, explain, or recall.")
    except Exception as exc:
        return tool_error(f"phi_memory failed: {type(exc).__name__}: {exc}")
