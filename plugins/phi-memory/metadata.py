"""Phi Memory metadata sidecar management."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import atomic_replace

from . import core

SIDECAR_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sidecar_path(store: Any, target: str) -> Path:
    return store._path_for(target).with_name(store._path_for(target).name + ".phi.json")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_hash(text: str) -> str:
    return hashlib.sha256(core.normalize_text(text).encode("utf-8")).hexdigest()


def memory_id(target: str, text: str) -> str:
    return f"{target}-{normalized_hash(text)[:16]}"


def safe_preview(text: str, limit: int = 160) -> str:
    return core._sanitize_for_diff(text).replace("\n", " ")[:limit]


def _entry_for(target: str, text: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = dict(existing or {})
    score = core.score_text(text, target=target)
    created = existing.get("created_at") or now_iso()
    return {
        "target": target,
        "text_hash": text_hash(text),
        "normalized_hash": normalized_hash(text),
        "safe_preview": safe_preview(text),
        "created_at": created,
        "updated_at": now_iso(),
        "last_accessed_at": existing.get("last_accessed_at"),
        "access_count": int(existing.get("access_count", 0) or 0),
        "review_count": int(existing.get("review_count", 0) or 0),
        "review_interval_index": int(existing.get("review_interval_index", 0) or 0),
        "next_review_after_interactions": int(existing.get("next_review_after_interactions", 1) or 1),
        "last_phi_score": round(score.phi_score, 4),
        "last_tier": score.tier,
        "last_action": existing.get("last_action") or "keep",
        "tags": list(existing.get("tags") or []),
        "related_memory_ids": list(existing.get("related_memory_ids") or []),
        "supersedes_memory_ids": list(existing.get("supersedes_memory_ids") or []),
        "source_session_id": existing.get("source_session_id"),
        "skill_candidate": bool(existing.get("skill_candidate", False)) or score.memory_type == core.MemoryType.SKILL_CANDIDATE.value,
        "sensitive": bool(score.is_secret_or_sensitive),
        "stability_score": float(existing.get("stability_score", score.stability_score) or 0.0),
        "confidence_score": float(existing.get("confidence_score", score.confidence_score) or 0.0),
    }


def build_sidecar(store: Any, target: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    path = store._path_for(target)
    previous_entries = (previous or {}).get("entries", {}) if isinstance(previous, dict) else {}
    entries: dict[str, Any] = {}
    for text in store._entries_for(target):
        mid = memory_id(target, text)
        entries[mid] = _entry_for(target, text, previous_entries.get(mid))
    ts = now_iso()
    return {
        "version": SIDECAR_VERSION,
        "target": target,
        "memory_file": str(path),
        "created_at": (previous or {}).get("created_at") if isinstance(previous, dict) else ts,
        "updated_at": ts,
        "entries": entries,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    atomic_replace(tmp, path)


def load_sidecar(store: Any, target: str) -> dict[str, Any]:
    path = sidecar_path(store, target)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else build_sidecar(store, target)
    except Exception:
        return build_sidecar(store, target)


def read_sidecar_raw(store: Any, target: str) -> tuple[str, dict[str, Any] | None, str | None]:
    path = sidecar_path(store, target)
    if not path.exists():
        return "missing", None, None
    try:
        return "ok", json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return "corrupt", None, str(exc)


def rebuild_sidecar(store: Any, target: str) -> dict[str, Any]:
    path = sidecar_path(store, target)
    status, previous, _error = read_sidecar_raw(store, target)
    payload = build_sidecar(store, target, previous if status == "ok" else None)
    backup_path = None
    if path.exists():
        backup_path = str(path.with_name(path.name + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")))
        try:
            shutil.copy2(path, backup_path)
        except (OSError, IOError) as exc:
            return {
                "success": False,
                "path": str(path),
                "backup_path": backup_path,
                "error": f"Sidecar backup failed; sidecar was not rebuilt: {exc}",
            }
    _atomic_write_json(path, payload)
    return {"success": True, "path": str(path), "backup_path": backup_path, "entries": len(payload["entries"])}


def sidecar_status(store: Any, target: str) -> dict[str, Any]:
    path = sidecar_path(store, target)
    status, payload, error = read_sidecar_raw(store, target)
    if status == "ok" and payload is not None:
        expected = {memory_id(target, text) for text in store._entries_for(target)}
        actual = set((payload.get("entries") or {}).keys())
        if expected != actual:
            status = "stale"
    return {"success": True, "target": target, "path": str(path), "status": status, "error": error}


def validate_sidecar(store: Any, target: str) -> dict[str, Any]:
    status = sidecar_status(store, target)
    valid = status["status"] == "ok"
    return {"success": True, "valid": valid, **status}


def update_entry(store: Any, target: str, mid: str, updates: dict[str, Any]) -> None:
    payload = load_sidecar(store, target)
    if mid not in payload.get("entries", {}):
        payload = build_sidecar(store, target, payload)
    if mid in payload["entries"]:
        payload["entries"][mid].update(updates)
        payload["updated_at"] = now_iso()
        _atomic_write_json(sidecar_path(store, target), payload)


def increment_access(store: Any, target: str, mids: list[str]) -> None:
    if not mids:
        return
    payload = load_sidecar(store, target)
    changed = False
    for mid in mids:
        entry = payload.get("entries", {}).get(mid)
        if not entry:
            continue
        entry["access_count"] = int(entry.get("access_count", 0) or 0) + 1
        entry["last_accessed_at"] = now_iso()
        changed = True
    if changed:
        payload["updated_at"] = now_iso()
        _atomic_write_json(sidecar_path(store, target), payload)
