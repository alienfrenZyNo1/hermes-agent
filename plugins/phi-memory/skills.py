"""Skill-candidate detection and draft handoff for Phi Memory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from . import core, metadata

_PROCEDURAL_RE = re.compile(r"\b(when|workflow|steps?|checklist|run|then|deploy|debug|test|build|always do|procedure)\b", re.I)


def _score_skill_candidate(text: str) -> float:
    lowered = text.lower()
    score = 0.0
    if _PROCEDURAL_RE.search(text):
        score += 0.35
    if any(sep in lowered for sep in (" then ", "->", "1.", "2.", "first", "next")):
        score += 0.3
    if any(word in lowered for word in ("deploy", "debug", "test", "build", "api", "integration")):
        score += 0.2
    if core.sensitivity_score_for_text(text)[1]:
        score -= 0.1
    return max(0.0, min(1.0, score))


def find_skill_candidates(store: Any, target: str = "memory") -> dict[str, Any]:
    candidates = []
    sidecar = metadata.load_sidecar(store, target)
    sidecar_entries = sidecar.get("entries", {}) if isinstance(sidecar, dict) else {}
    for text in store._entries_for(target):
        mid = metadata.memory_id(target, text)
        sidecar_entry = sidecar_entries.get(mid, {})
        if sidecar_entry.get("last_action") == "dismiss_skill_candidate":
            continue
        score = _score_skill_candidate(text)
        if score >= 0.45:
            candidates.append({
                "candidate_id": mid,
                "memory_id": mid,
                "score": round(score, 3),
                "safe_preview": metadata.safe_preview(text),
                "suggested_skill_name": _safe_name(text),
                "suggested_replacement": f"Procedure moved to skill: {_safe_name(text)}",
            })
    return {"success": True, "target": target, "candidates": candidates, "count": len(candidates)}


def _safe_name(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:6]
    name = "-".join(words) or "phi-memory-skill-draft"
    return name[:64]


def draft_skill(store: Any, target: str, candidate_id: str, write_file: bool = False) -> dict[str, Any]:
    match = None
    for text in store._entries_for(target):
        if metadata.memory_id(target, text) == candidate_id:
            match = text
            break
    if not match:
        return {"success": False, "error": f"Unknown candidate_id: {candidate_id}"}
    name = _safe_name(match)
    content = (
        "---\n"
        f"name: {name}\n"
        "description: Draft skill generated from Phi Memory procedural candidate. Review before installing.\n"
        "created_by: phi-memory-draft\n"
        "---\n\n"
        f"# {name}\n\n"
        "## Source\n\n"
        f"source_memory_ids: [{candidate_id}]\n\n"
        "## Draft procedure\n\n"
        f"{core._sanitize_for_diff(match)}\n\n"
        "## Review notes\n\n"
        "- This is a draft only. Do not install without explicit review.\n"
        "- Verify commands, paths, and secrets before promotion.\n"
    )
    path = None
    write_error = None
    if write_file:
        try:
            drafts = get_hermes_home() / "skills" / "drafts"
            drafts.mkdir(parents=True, exist_ok=True)
            out = drafts / f"{name}.md"
            out.write_text(content, encoding="utf-8")
            path = str(out)
        except (OSError, IOError) as exc:
            write_error = f"Draft file could not be written; returning draft text only: {exc}"
    return {"success": True, "candidate_id": candidate_id, "skill_name": name, "content": content, "path": path, "write_error": write_error}


def dismiss_candidate(store: Any, target: str, candidate_id: str) -> dict[str, Any]:
    metadata.update_entry(store, target, candidate_id, {"skill_candidate": False, "last_action": "dismiss_skill_candidate"})
    return {"success": True, "candidate_id": candidate_id, "dismissed": True}
