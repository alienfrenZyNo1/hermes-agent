"""Active-memory recall with optional session archive fallback."""

from __future__ import annotations

import json
from typing import Any, Callable

from . import core, metadata


def _default_session_searcher(query: str, limit: int = 3) -> list[dict[str, Any]]:
    from tools.session_search_tool import session_search

    raw = session_search(query=query, limit=limit)
    payload = json.loads(raw)
    results = []
    for item in payload.get("results", []) or payload.get("sessions", []) or []:
        text = str(item.get("snippet") or item.get("title") or item.get("preview") or "")
        if not text and item.get("messages"):
            text = str(item["messages"][0].get("content", ""))
        results.append({
            "source": "session_archive",
            "score": 0.5,
            "text": core._sanitize_for_diff(text)[:240],
            "session_id": item.get("session_id"),
        })
    return results


def recall_with_fallback(
    store: Any,
    query: str,
    target: str = "memory",
    include_session: bool = False,
    active_only: bool = False,
    session_searcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    cfg = core.phi_config()
    threshold = float(cfg.get("recall_active_confidence_threshold", 0.45) or 0.45)
    active = core.recall(store, query, target=target)
    hits = []
    accessed_ids = []
    for hit in active.get("hits", []):
        source = "user_memory" if target == "user" else "active_memory"
        text = hit.get("text", "")
        mid = metadata.memory_id(target, text)
        accessed_ids.append(mid)
        safe_hit = {**hit, "text": core._sanitize_for_diff(str(text)), "source": source, "memory_id": mid}
        hits.append(safe_hit)
    if accessed_ids:
        metadata.increment_access(store, target, accessed_ids)
    max_active = max([float(h.get("score", 0) or 0) for h in hits], default=0.0)
    should_search_session = bool(include_session or (not active_only and cfg.get("recall_session_fallback_enabled", True) and max_active < threshold))
    session_error = None
    if should_search_session:
        try:
            searcher = session_searcher or _default_session_searcher
            for result in searcher(query, 3) or []:
                safe = core._sanitize_for_diff(str(result.get("text", "")))[:240]
                hits.append({
                    "source": "session_archive",
                    "score": float(result.get("score", 0.5) or 0.5),
                    "text": safe,
                    "session_id": result.get("session_id"),
                    "suggested_action": "promote_candidate" if float(result.get("score", 0.5) or 0.5) >= threshold else "archive_hint",
                })
        except Exception as exc:
            session_error = f"session search unavailable: {type(exc).__name__}: {exc}"
    return {
        "success": True,
        "query": query,
        "target": target,
        "hits": hits,
        "active_confidence": round(max_active, 4),
        "session_search_used": should_search_session and session_error is None,
        "session_error": session_error,
    }
