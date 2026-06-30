"""Phi Memory governance helpers.

This module does not introduce a separate memory backend.  It evaluates and
reviews the existing built-in MEMORY.md / USER.md stores using golden-ratio
rules so storage remains backward-compatible and prompt-cache safe.
"""

from __future__ import annotations

import difflib
import math
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

PHI = 1.61803398875
PHI_MAJOR = 1 / PHI
PHI_MINOR = 1 / (PHI * PHI)
PHI_HARD_WARNING = PHI / 2
PHI_EMERGENCY = 0.95

FIBONACCI_REVIEW_INTERVALS = (1, 2, 3, 5, 8, 13)


def phi_config() -> Dict[str, Any]:
    """Return Phi Memory config with safe defaults filled in."""
    defaults: Dict[str, Any] = {
        "enabled": True,
        "safe_apply_enabled": True,
        "auto_safe_cleanup_on_write_pressure": False,
        "auto_safe_cleanup_threshold": PHI_EMERGENCY,
        "metadata_sidecar_enabled": True,
        "metadata_sidecar_version": 1,
        "fibonacci_review_enabled": True,
        "fibonacci_review_intervals": list(FIBONACCI_REVIEW_INTERVALS),
        "recall_session_fallback_enabled": True,
        "recall_active_confidence_threshold": 0.45,
        "skill_candidate_detection_enabled": True,
        "skill_candidate_draft_enabled": True,
        "semantic_compression_enabled": True,
        "semantic_compression_apply_enabled": False,
        "dashboard_enabled": True,
    }
    try:
        from hermes_cli.config import load_config

        config = load_config()
        memory_config = config.get("memory", {}) if isinstance(config, dict) else {}
        # Backward compatibility: legacy memory.phi works when no explicit
        # top-level phi_memory block exists. If both are present in the user's
        # config file, prefer the new plugin config.
        raw_legacy = memory_config.get("phi", {}) if isinstance(memory_config, dict) else {}
        if isinstance(raw_legacy, dict):
            defaults.update(raw_legacy)
        explicit_plugin_config = False
        try:
            from hermes_constants import get_hermes_home
            import yaml
            cfg_path = get_hermes_home() / "config.yaml"
            raw_user = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
            explicit_plugin_config = isinstance(raw_user, dict) and isinstance(raw_user.get("phi_memory"), dict)
        except Exception:
            explicit_plugin_config = False
        raw_plugin = config.get("phi_memory", {}) if isinstance(config, dict) else {}
        if explicit_plugin_config and isinstance(raw_plugin, dict):
            defaults.update(raw_plugin)
    except Exception:
        pass
    return defaults


def phi_enabled() -> bool:
    """Return whether Phi Memory governance is enabled in config.

    Config is optional on tool paths, so failures default to enabled for the
    new feature while preserving an explicit ``memory.phi.enabled: false`` opt-out.
    """
    return phi_config().get("enabled") is not False


class MemoryTier(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ARCHIVED = "archived"


class MemoryType(str, Enum):
    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    ENVIRONMENT_FACT = "environment_fact"
    DECISION = "decision"
    CORRECTION = "correction"
    WORKFLOW_LESSON = "workflow_lesson"
    OPEN_LOOP = "open_loop"
    RISK = "risk"
    COMPLETED_WORK = "completed_work"
    SKILL_CANDIDATE = "skill_candidate"


class CompressionLevel(str, Enum):
    RAW = "raw"
    DETAILED = "detailed"
    SEMANTIC = "semantic"
    CORE = "core"


@dataclass
class PhiMemoryCandidate:
    id: str
    text: str
    source: str = "memory_tool"
    source_session_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""
    last_accessed_at: str = ""
    access_count: int = 0
    memory_type: str = MemoryType.PROJECT_FACT.value
    tier: str = MemoryTier.SHORT_TERM.value
    importance_score: float = 0.0
    recency_score: float = 0.0
    stability_score: float = 0.0
    frequency_score: float = 0.0
    confidence_score: float = 0.0
    sensitivity_score: float = 0.0
    current_project_relevance_score: float = 0.0
    explicit_user_request_score: float = 0.0
    phi_score: float = 0.0
    compression_level: str = CompressionLevel.DETAILED.value
    tags: List[str] = field(default_factory=list)
    related_memory_ids: List[str] = field(default_factory=list)
    supersedes_memory_ids: List[str] = field(default_factory=list)
    is_secret_or_sensitive: bool = False
    should_save: bool = False
    should_promote: bool = False
    should_compress: bool = False
    should_remove: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Round scores for stable CLI/test output.
        for key, value in list(data.items()):
            if key.endswith("_score") and isinstance(value, float):
                data[key] = round(value, 4)
        return data


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def average(*values: float) -> float:
    vals = [_clamp(v) for v in values]
    return sum(vals) / len(vals) if vals else 0.0


def phi_score(
    *,
    importance_score: float,
    stability_score: float,
    confidence_score: float,
    frequency_score: float,
    recency_score: float,
    current_project_relevance_score: float = 0.0,
    explicit_user_request_score: float = 0.0,
) -> float:
    """Return golden-ratio score balancing durable and active value."""
    durable_value = average(
        importance_score,
        stability_score,
        confidence_score,
        frequency_score,
    )
    active_value = average(
        recency_score,
        current_project_relevance_score,
        explicit_user_request_score,
    )
    return _clamp((PHI_MAJOR * durable_value) + (PHI_MINOR * active_value))


def pressure_level(current_chars: int, limit: int) -> Dict[str, Any]:
    ratio = (current_chars / limit) if limit > 0 else 0.0
    threshold_ratio = round(ratio, 3)
    if ratio >= PHI_EMERGENCY:
        level = "emergency"
        action = "emergency_compaction_before_new_writes"
    elif ratio >= PHI_HARD_WARNING:
        level = "consolidate"
        action = "actively_consolidate_before_adding"
    elif threshold_ratio >= round(PHI_MAJOR, 3):
        level = "review"
        action = "review_consolidation_candidates"
    else:
        level = "healthy"
        action = "no_pressure_action_required"
    return {
        "ratio": round(ratio, 4),
        "percent": round(ratio * 100, 1),
        "level": level,
        "action": action,
        "thresholds": {
            "review": round(PHI_MAJOR, 4),
            "consolidate": round(PHI_HARD_WARNING, 4),
            "emergency": PHI_EMERGENCY,
        },
    }


_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?(?!\[REDACTED)[^\s'\"]{12,}", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
]


def sensitivity_score_for_text(text: str) -> Tuple[float, bool, str]:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return 1.0, True, "Looks like a credential, token, private key, or secret-bearing assignment."
    lowered = text.lower()
    sensitive_terms = ("recovery phrase", "seed phrase", "private key", "password", "api key")
    if any(term in lowered for term in sensitive_terms):
        return 0.85, True, "Mentions sensitive credential material."
    return 0.0, False, "No obvious secret pattern."


def classify_memory_type(text: str, target: str = "memory") -> str:
    lowered = text.lower()
    if target == "user" or "user prefers" in lowered or "user wants" in lowered:
        return MemoryType.USER_PREFERENCE.value
    if any(k in lowered for k in ("correction", "instead", "don't", "do not", "prefer")):
        return MemoryType.CORRECTION.value
    if any(k in lowered for k in ("workflow", "steps", "run ", "command", "deploy", "debug")):
        return MemoryType.WORKFLOW_LESSON.value
    if any(k in lowered for k in ("todo", "open loop", "currently", "failing test")):
        return MemoryType.OPEN_LOOP.value
    if any(k in lowered for k in ("risk", "unsafe", "blocked", "secret")):
        return MemoryType.RISK.value
    if any(k in lowered for k in ("repo", "project", "uses", "path", "deployment")):
        return MemoryType.PROJECT_FACT.value
    return MemoryType.ENVIRONMENT_FACT.value


def score_text(
    text: str,
    *,
    target: str = "memory",
    explicit_user_request: bool = False,
    current_project_relevance_score: float = 0.0,
    frequency_score: float = 0.0,
    existing_entries: Optional[Sequence[str]] = None,
) -> PhiMemoryCandidate:
    """Build a deterministic candidate evaluation for a proposed memory entry."""
    stripped = " ".join((text or "").split())
    mem_type = classify_memory_type(stripped, target=target)
    sensitivity, is_sensitive, sensitivity_reason = sensitivity_score_for_text(stripped)

    lowered = stripped.lower()
    importance = 0.5
    stability = 0.5
    confidence = 0.6
    recency = 0.75
    explicit = 1.0 if explicit_user_request or "remember" in lowered else 0.0

    if mem_type == MemoryType.USER_PREFERENCE.value:
        importance += 0.35
        stability += 0.35
        confidence += 0.2
        frequency_score = max(frequency_score, 0.5)
        current_project_relevance_score = max(current_project_relevance_score, 0.5)
    elif mem_type in {MemoryType.CORRECTION.value, MemoryType.RISK.value}:
        importance += 0.25
        stability += 0.15
        confidence += 0.15
    elif mem_type == MemoryType.WORKFLOW_LESSON.value:
        importance += 0.2
        stability += 0.1
    elif mem_type == MemoryType.OPEN_LOOP.value:
        importance += 0.2
        stability -= 0.05
        recency += 0.2
        current_project_relevance_score = max(current_project_relevance_score, 0.7)
    elif mem_type == MemoryType.COMPLETED_WORK.value:
        importance -= 0.15
        stability -= 0.1

    if any(k in lowered for k in ("temporary", "one-off", "today", "currently", "failing test")):
        stability -= 0.2
    if any(k in lowered for k in ("always", "prefers", "stable", "main repo", "project uses")):
        stability += 0.15
    if len(stripped) > 280:
        importance -= 0.05
        confidence -= 0.05

    duplicate_ids: List[str] = []
    supersedes_ids: List[str] = []
    if existing_entries:
        normalized_new = normalize_text(stripped)
        for idx, entry in enumerate(existing_entries):
            normalized_existing = normalize_text(entry)
            if normalized_new == normalized_existing:
                duplicate_ids.append(f"existing:{idx}")
            elif contradiction_key(stripped) and contradiction_key(stripped) == contradiction_key(entry):
                supersedes_ids.append(f"existing:{idx}")

    score = phi_score(
        importance_score=importance,
        stability_score=stability,
        confidence_score=confidence,
        frequency_score=frequency_score,
        recency_score=recency,
        current_project_relevance_score=current_project_relevance_score,
        explicit_user_request_score=explicit,
    )

    tier = MemoryTier.LONG_TERM.value if score >= PHI_MAJOR else (
        MemoryTier.SHORT_TERM.value if score >= PHI_MINOR else MemoryTier.ARCHIVED.value
    )
    should_save = score >= PHI_MINOR and not is_sensitive and not duplicate_ids
    reason_parts = [
        f"phi_score={score:.3f}",
        f"durable/active split={PHI_MAJOR:.3f}/{PHI_MINOR:.3f}",
        f"tier={tier}",
        sensitivity_reason,
    ]
    if duplicate_ids:
        reason_parts.append("Rejected as duplicate of active memory.")
    if supersedes_ids:
        reason_parts.append("Newer entry appears to supersede an older related preference/fact.")
    if explicit:
        reason_parts.append("Explicit remember request boosted active value but did not bypass safety checks.")

    return PhiMemoryCandidate(
        id=stable_id(stripped),
        text=stripped,
        memory_type=mem_type,
        tier=tier,
        importance_score=_clamp(importance),
        recency_score=_clamp(recency),
        stability_score=_clamp(stability),
        frequency_score=_clamp(frequency_score),
        confidence_score=_clamp(confidence),
        sensitivity_score=sensitivity,
        current_project_relevance_score=_clamp(current_project_relevance_score),
        explicit_user_request_score=explicit,
        phi_score=score,
        compression_level=CompressionLevel.CORE.value if tier == MemoryTier.LONG_TERM.value else CompressionLevel.DETAILED.value,
        supersedes_memory_ids=supersedes_ids,
        related_memory_ids=duplicate_ids,
        is_secret_or_sensitive=is_sensitive,
        should_save=should_save,
        should_promote=score >= PHI_MAJOR and not is_sensitive,
        should_compress=score < PHI_MAJOR and len(stripped) > 160,
        should_remove=score < PHI_MINOR or is_sensitive or bool(duplicate_ids),
        reason=" ".join(reason_parts),
    )


def stable_id(text: str) -> str:
    import hashlib

    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()[:12]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def contradiction_key(text: str) -> str:
    """Return a coarse key for entries that should usually supersede older ones."""
    lowered = normalize_text(text)
    # Preferences with the same trailing scope ("for debugging", "in VS Code")
    # supersede each other even when the preferred value changes.
    m = re.search(r"^user prefers\s+.+?\s+(for|in|when)\s+(.+)$", lowered)
    if m:
        return f"user prefers {m.group(1)} {m.group(2)}"[:96]
    m = re.search(r"^user wants\s+.+?\s+(for|in|when)\s+(.+)$", lowered)
    if m:
        return f"user wants {m.group(1)} {m.group(2)}"[:96]
    patterns = [
        r"^(project [^:]+)\s+(?:uses|is|runs)\b",
        r"^([^:]{3,80})\s*:\s*",
    ]
    for pattern in patterns:
        m = re.search(pattern, lowered)
        if m:
            return " ".join(g for g in m.groups() if g)[:96]
    return ""


def entry_score(entry: str, *, target: str, index: int, total: int) -> PhiMemoryCandidate:
    """Score an existing entry, lightly biasing newer entries by position."""
    recency = 1.0 - (index / max(total, 1)) * PHI_MINOR
    freq = min(1.0, max(0.0, entry.lower().count("user") * 0.15))
    candidate = score_text(
        entry,
        target=target,
        frequency_score=freq,
        current_project_relevance_score=0.25,
    )
    candidate.recency_score = round(_clamp(recency), 4)
    candidate.phi_score = phi_score(
        importance_score=candidate.importance_score,
        stability_score=candidate.stability_score,
        confidence_score=candidate.confidence_score,
        frequency_score=candidate.frequency_score,
        recency_score=candidate.recency_score,
        current_project_relevance_score=candidate.current_project_relevance_score,
        explicit_user_request_score=candidate.explicit_user_request_score,
    )
    candidate.should_promote = candidate.phi_score >= PHI_MAJOR and not candidate.is_secret_or_sensitive
    candidate.tier = MemoryTier.LONG_TERM.value if candidate.should_promote else (
        MemoryTier.SHORT_TERM.value if candidate.phi_score >= PHI_MINOR else MemoryTier.ARCHIVED.value
    )
    return candidate


def _entries_for_store(store: Any, target: str) -> List[str]:
    if hasattr(store, "_entries_for"):
        return list(store._entries_for(target))
    return []


def _char_count(entries: Sequence[str], delimiter: str = "\n§\n") -> int:
    return len(delimiter.join(entries)) if entries else 0


def review_store(store: Any, *, target: str = "memory", dry_run: bool = True) -> Dict[str, Any]:
    entries = _entries_for_store(store, target)
    limit = store._char_limit(target) if hasattr(store, "_char_limit") else 0
    current = _char_count(entries)
    pressure = pressure_level(current, limit)
    candidates = [score_text(e, target=target, current_project_relevance_score=0.25) for e in entries]
    ranked = sorted(candidates, key=lambda c: c.phi_score, reverse=True)
    keep_count = math.ceil(len(ranked) * PHI_MAJOR) if ranked else 0
    keep_ids = {c.id for c in ranked[:keep_count]}

    proposals: List[Dict[str, Any]] = []
    seen: Dict[str, PhiMemoryCandidate] = {}
    for candidate in candidates:
        norm = normalize_text(candidate.text)
        action = "keep"
        if norm in seen:
            action = "remove_duplicate"
        elif candidate.is_secret_or_sensitive:
            action = "remove_sensitive"
        elif candidate.id not in keep_ids and len(candidate.text) > 80:
            action = "compress_to_semantic_summary"
        elif candidate.phi_score >= PHI_MAJOR:
            action = "promote_or_keep_long_term"
        elif candidate.phi_score < PHI_MINOR:
            action = "archive_to_session_search"
        seen[norm] = candidate
        proposals.append({
            "id": candidate.id,
            "action": action,
            "tier": candidate.tier,
            "phi_score": round(candidate.phi_score, 4),
            "text_preview": _sanitize_for_diff(candidate.text)[:120],
            "reason": candidate.reason,
        })

    return {
        "success": True,
        "dry_run": dry_run,
        "target": target,
        "usage": {"current_chars": current, "limit": limit, **pressure},
        "phi": {
            "PHI": PHI,
            "PHI_MAJOR": PHI_MAJOR,
            "PHI_MINOR": PHI_MINOR,
            "active_split": {"long_term": PHI_MAJOR, "short_term": PHI_MINOR},
            "fibonacci_review_intervals": FIBONACCI_REVIEW_INTERVALS,
        },
        "entry_count": len(entries),
        "keep_top_count": keep_count,
        "proposals": proposals,
        "note": "Dry-run only; no memory files were changed." if dry_run else "Review generated.",
    }


def _trim_entry(entry: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in (entry or "").splitlines()]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _is_obviously_broken_fragment(entry: str) -> bool:
    stripped = (entry or "").strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if stripped in {"...", "…", "-", "—", "§"}:
        return True
    if lowered in {"truncated", "[truncated]", "continued", "todo"}:
        return True
    if len(stripped) < 8 and not re.search(r"[A-Za-z0-9]{3,}", stripped):
        return True
    return False


_REDACTION_PATTERNS: Tuple[Tuple[re.Pattern[str], str | Callable[[Any], str]], ...] = (
    (re.compile(r"/[^\s`'\"]*/\.secrets/[^\s`'\"]+"), "[REDACTED_SECRET_PATH]"),
    (re.compile(r"[A-Za-z]:\\[^\s`'\"]*\\\.secrets\\[^\s`'\"]+"), "[REDACTED_SECRET_PATH]"),
    (re.compile(r"/[^\s`'\"]*(?:service[-_]?account|credentials?|creds)[^\s`'\"]*\.json", re.I), "[REDACTED_SECRET_PATH]"),
    (re.compile(r"[A-Za-z]:\\[^\s`'\"]*(?:service[-_]?account|credentials?|creds)[^\s`'\"]*\.json", re.I), "[REDACTED_SECRET_PATH]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.I | re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s'\";]{12,}", re.I), lambda m: re.sub(r"[:=].*", "=[REDACTED_SECRET]", m.group(0))),
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b"), "[REDACTED_SECRET]"),
)


def redact_sensitive_text(text: str) -> Tuple[str, bool]:
    redacted = text or ""
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted, redacted != (text or "")


def _sanitize_for_diff(text: str) -> str:
    redacted, _ = redact_sensitive_text(text)
    return redacted


def apply_safe_cleanup(store: Any, *, target: str = "memory", already_locked: bool = False) -> Dict[str, Any]:
    """Apply deterministic low-risk Phi Memory cleanup.

    This never performs semantic summarisation or LLM rewriting.  It only trims
    whitespace, removes empty/broken fragments, removes normalized duplicates,
    and redacts obvious secret values/paths.  A timestamped backup is written
    beside the memory file before any mutation.
    """
    if target not in {"memory", "user"}:
        return {"success": False, "error": "Invalid --target for Phi Memory. Use --target memory or --target user."}
    cfg = phi_config()
    if cfg.get("safe_apply_enabled") is False:
        return {"success": False, "error": "Phi Memory safe apply is disabled by memory.phi.safe_apply_enabled=false."}
    if not hasattr(store, "_path_for") or not hasattr(store, "_write_file"):
        return {"success": False, "error": "Memory store does not support safe cleanup."}

    path: Path = store._path_for(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> Dict[str, Any]:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        from tools.memory_tool import ENTRY_DELIMITER

        old_entries = raw.split(ENTRY_DELIMITER) if raw.strip() else []
        old_rendered_raw = ENTRY_DELIMITER.join(old_entries) if old_entries else ""
        old_chars = len(old_rendered_raw)
        limit = store._char_limit(target) if hasattr(store, "_char_limit") else 0
        seen: set[str] = set()
        new_entries: List[str] = []
        removed = 0
        redacted_count = 0
        actions: List[str] = []
        for entry in old_entries:
            trimmed = _trim_entry(entry)
            if _is_obviously_broken_fragment(trimmed):
                removed += 1
                actions.append("removed empty/broken fragment")
                continue
            redacted, was_redacted = redact_sensitive_text(trimmed)
            if was_redacted:
                redacted_count += 1
                actions.append("redacted suspected sensitive value/path")
            norm = normalize_text(redacted)
            if norm in seen:
                removed += 1
                actions.append("removed duplicate")
                continue
            seen.add(norm)
            new_entries.append(redacted)

        if old_entries and not new_entries:
            return {"success": False, "error": "Refusing safe cleanup because it would leave the memory file empty."}

        new_rendered = ENTRY_DELIMITER.join(new_entries)
        new_chars = len(new_rendered)
        pressure_before = pressure_level(old_chars, limit)
        pressure_after = pressure_level(new_chars, limit)
        diff = "".join(difflib.unified_diff(
            _sanitize_for_diff(old_rendered_raw).splitlines(keepends=True),
            _sanitize_for_diff(new_rendered).splitlines(keepends=True),
            fromfile=f"{path.name} before",
            tofile=f"{path.name} after",
        ))

        report: Dict[str, Any] = {
            "success": True,
            "target": target,
            "applied": False,
            "old_chars": old_chars,
            "new_chars": new_chars,
            "percent_before": pressure_before["percent"],
            "percent_after": pressure_after["percent"],
            "pressure_before": pressure_before,
            "pressure_after": pressure_after,
            "entries_removed": removed,
            "entries_redacted": redacted_count,
            "backup_path": "",
            "diff": diff,
            "actions": actions,
            "note": "No safe cleanup changes were needed.",
        }
        if new_rendered == old_rendered_raw:
            store._set_entries(target, list(new_entries))
            return report

        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak.{ts}")
        suffix = 0
        while backup_path.exists():
            suffix += 1
            backup_path = path.with_name(f"{path.name}.bak.{ts}.{suffix}")
        try:
            if path.exists():
                shutil.copy2(path, backup_path)
            else:
                backup_path.write_text("", encoding="utf-8")
        except (OSError, IOError) as exc:
            report.update({
                "success": False,
                "applied": False,
                "backup_path": str(backup_path),
                "error": f"Backup creation failed; memory file was not changed: {exc}",
                "note": "Safe cleanup aborted before writing because backup creation failed.",
            })
            return report
        store._write_file(path, new_entries)
        store._set_entries(target, list(new_entries))
        report.update({
            "applied": True,
            "backup_path": str(backup_path),
            "note": "Applied deterministic safe cleanup only; no semantic rewrite was performed.",
        })
        return report

    if already_locked:
        return _run()
    lock_fn = getattr(store, "_file_lock", None)
    if lock_fn is None:
        return _run()
    with lock_fn(path):
        return _run()


def recall(store: Any, query: str, *, target: str = "memory", limit: int = 5) -> Dict[str, Any]:
    entries = _entries_for_store(store, target)
    q_terms = set(re.findall(r"[a-z0-9_/-]+", query.lower()))
    hits = []
    for entry in entries:
        terms = set(re.findall(r"[a-z0-9_/-]+", entry.lower()))
        overlap = len(q_terms & terms) / max(1, len(q_terms))
        candidate = score_text(entry, target=target, current_project_relevance_score=overlap)
        combined = (PHI_MAJOR * overlap) + (PHI_MINOR * candidate.phi_score)
        if overlap > 0:
            hits.append({
                "id": candidate.id,
                "score": round(combined, 4),
                "source": f"active:{target}",
                "text": entry,
                "source_hint": "Active memory hit. Use session_search for older details if this is insufficient.",
            })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"success": True, "query": query, "hits": hits[:limit], "searched": [f"active:{target}"], "archive_hint": "Use session_search for full transcript/archive recall."}


def explain_text(text: str, *, target: str = "memory", existing_entries: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    candidate = score_text(text, target=target, explicit_user_request="remember" in text.lower(), existing_entries=existing_entries)
    return {"success": True, "candidate": candidate.to_dict()}


def handle_phi_memory_args(store: Any, args: Sequence[str]) -> str:
    """Return text for `/memory phi ...` style commands."""
    if not phi_enabled():
        return "Phi Memory is disabled by memory.phi.enabled=false. Existing memory commands still use the built-in MEMORY.md/USER.md behavior."
    command = args[0].lower() if args else "status"
    target = "memory"
    if "--target" in args:
        target = _value_after(args, "--target")
        if target not in {"memory", "user"}:
            return "Invalid --target for Phi Memory. Use --target memory or --target user."
    wants_json = "--json" in args
    apply_safe = "--apply-safe" in args
    if command in {"status", "review", "compress"}:
        if command == "compress" and apply_safe:
            report = apply_safe_cleanup(store, target=target)
            if wants_json:
                import json
                return json.dumps(report, indent=2, ensure_ascii=False)
            return format_safe_cleanup_report(report)
        report = review_store(store, target=target, dry_run=True)
        if command == "compress":
            report["mode"] = "compress"
            report["note"] = "Compression is currently proposal-only; no memory files were changed."
        if wants_json:
            import json
            return json.dumps(report, indent=2, ensure_ascii=False)
        return format_phi_report(report)
    if command == "explain":
        text = _free_text_after_command(args[1:])
        report = explain_text(text, target=target, existing_entries=_entries_for_store(store, target))
        if wants_json:
            import json
            return json.dumps(report, indent=2, ensure_ascii=False)
        c = report["candidate"]
        return f"Phi score: {c['phi_score']:.3f} — tier={c['tier']} — save={c['should_save']}\n{c['reason']}"
    if command == "recall":
        query = _free_text_after_command(args[1:])
        report = recall(store, query, target=target)
        if wants_json:
            import json
            return json.dumps(report, indent=2, ensure_ascii=False)
        lines = [f"Phi recall: {report['query']}"]
        for hit in report.get("hits", []):
            lines.append(f"- [{hit['score']:.3f}] {hit['text']}")
        if not report.get("hits"):
            lines.append("No active memory hit. Use session_search for archive recall.")
        return "\n".join(lines)
    return "Unknown /memory phi subcommand. Use: status, review, compress, explain, recall."


def _value_after(args: Sequence[str], flag: str) -> str:
    try:
        idx = list(args).index(flag)
        return args[idx + 1]
    except (ValueError, IndexError):
        return ""


def _free_text_after_command(args: Sequence[str]) -> str:
    skip_next = False
    kept: List[str] = []
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--target":
            skip_next = True
            continue
        if arg in {"--json", "--apply", "--apply-safe"}:
            continue
        kept.append(arg)
    return " ".join(kept)


def format_safe_cleanup_report(report: Dict[str, Any]) -> str:
    if not report.get("success"):
        return report.get("error", "Phi Memory safe cleanup failed.")
    lines = [
        f"Phi Memory safe cleanup {report.get('target', 'memory')} — applied={report.get('applied', False)}",
        f"Chars: {report.get('old_chars', 0):,} → {report.get('new_chars', 0):,}",
        f"Pressure: {report.get('percent_before', 0)}% → {report.get('percent_after', 0)}%",
        f"Entries removed: {report.get('entries_removed', 0)}",
        f"Entries redacted: {report.get('entries_redacted', 0)}",
        f"Backup: {report.get('backup_path') or 'not created (no changes)'}",
        "",
        "Unified diff summary:",
    ]
    diff = report.get("diff") or "(no diff)"
    lines.append(diff if len(diff) <= 4000 else diff[:4000] + "\n… (diff truncated)")
    return "\n".join(lines)


def format_phi_report(report: Dict[str, Any]) -> str:
    usage = report.get("usage", {})
    lines = [
        f"Phi Memory {report.get('target', 'memory')} — {usage.get('level', 'unknown')} ({usage.get('percent', 0)}%)",
        f"Chars: {usage.get('current_chars', 0):,}/{usage.get('limit', 0):,}",
        f"Split: long-term {PHI_MAJOR:.1%} / short-term {PHI_MINOR:.1%}",
        f"Dry run: {report.get('dry_run', True)}",
        "",
        "Top proposals:",
    ]
    if usage.get("level") == "emergency":
        lines.append(
            "Recommendation: run `memory phi compress --target "
            + report.get("target", "memory")
            + " --apply-safe` for deterministic cleanup; no changes are applied without --apply-safe."
        )
        lines.append("")
    for proposal in report.get("proposals", [])[:10]:
        lines.append(
            f"- {proposal['action']} [{proposal['phi_score']:.3f}] "
            f"{proposal['text_preview']}"
        )
    if not report.get("proposals"):
        lines.append("- No entries to review.")
    return "\n".join(lines)
