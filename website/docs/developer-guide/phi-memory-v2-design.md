---
title: "Phi Memory v2 design note"
description: "Incremental design for Phi Memory metadata, scheduling, recall, skill handoff, semantic proposals, and dashboard"
---

# Phi Memory v2 design note

## Current implementation state
- Phi Memory v1 is already an optional general plugin at `plugins/phi-memory/`, not a memory provider backend.
- Core coupling is intentionally small: `MemoryStore.add` exposes generic `pre_memory_write` / `post_memory_write` hooks, and legacy `hermes memory phi ...` / `/memory phi ...` shims dispatch to the plugin when enabled.
- Existing v1 safety behavior lives in plugin code: dry-run review/compress, deterministic `--apply-safe`, backup before mutation, duplicate cleanup, and secret/path redaction.

## Proposed v2 architecture
- Keep all v2 business logic inside `plugins/phi-memory/`.
- Split logic by concern rather than growing one large `core.py`:
  - `metadata.py` for optional sidecar load/rebuild/validate/atomic writes.
  - `review.py` for Fibonacci scheduling, due-review proposals, mark-reviewed.
  - `session_recall.py` for active-memory-first recall with optional session archive fallback.
  - `skills.py` for procedural memory detection and draft skill generation.
  - `semantic.py` for proposal-only semantic compression/diff output.
  - `dashboard.py` for stable JSON/text health summary.
- Extend `commands.py`, `tools.py`, and `schemas.py` to expose v2 actions, preserving v1 command behavior.
- Do not add Phi-specific core logic. If needed, use the existing generic memory hooks only.

## Files to change
- `plugins/phi-memory/core.py` — shared constants/scoring helpers only; small integrations for existing `recall`/`compress` behavior.
- New plugin modules: `metadata.py`, `review.py`, `session_recall.py`, `skills.py`, `semantic.py`, `dashboard.py`.
- `plugins/phi-memory/commands.py`, `tools.py`, `schemas.py`, `README.md`, `plugin.yaml`.
- `hermes_cli/config.py` for safe v2 defaults under `phi_memory`, retaining legacy `memory.phi` compatibility.
- Tests under `tests/plugins/test_phi_memory_plugin.py` and focused new plugin test files.
- Docs under `website/docs/user-guide/features/memory.md`, slash command reference, and this design note.

## Data model
- Keep `MEMORY.md` and `USER.md` as the source of truth and human-readable files.
- Store optional metadata sidecars beside them as `MEMORY.md.phi.json` and `USER.md.phi.json` to keep profile/memory-file locality and copy/backup behavior simple.
- Stable memory IDs derive from normalized text hash plus target. Sidecar entries store hashes, redacted `safe_preview`, counters, scores, review interval index, next review threshold, tags, relationships, source session ID, skill-candidate flag, and sensitivity flag.
- Missing/corrupt/stale sidecars are non-fatal. Rebuild safely from current memory entries without mutating `MEMORY.md`/`USER.md`.

## Safety risks and controls
- Semantic compression remains proposal-only. No semantic apply path will be added in v2.
- Automatic mutation remains limited to existing deterministic `--apply-safe` cleanup.
- Sidecar writes use atomic write and make a timestamped backup before overwriting existing sidecars.
- Sidecar and proposal outputs store redacted previews/hashes, never raw rejected sensitive text.
- Session fallback returns compact source-labelled hints only and never promotes archive results automatically.
- Skill handoff only writes draft skill text/files; it never installs/enables skills silently.
- Plugin-disabled mode leaves normal memory writes governed only by core behavior and Phi commands unavailable/clearly disabled.

## Test plan
- Metadata: create/missing/corrupt/stale sidecar, redaction, access counts, validate/rebuild commands.
- Fibonacci review: interval progression 1→2→3→5→8→13, due detection, mark-reviewed, no automatic deletion.
- Session fallback: active hit, weak active fallback, `--active-only`, `--include-session`, unavailable search degradation.
- Skill handoff: procedural detection, non-procedural rejection, redacted draft generation, no silent install.
- Semantic proposals: proposal-only, diff, budget, preservation of exact facts/paths/DB names, redaction, no mutation.
- Dashboard: stable JSON, pressure, sidecar health, due count, skill candidates, duplicates, recommendations.
- Regression: v1 `--apply-safe`, dry-run no mutation, plugin disabled no governance, legacy `memory.phi` config.

## Rollback plan
- Revert the v2 commit(s) to restore the v1 plugin.
- Since sidecars/proposals are optional and separate from `MEMORY.md`/`USER.md`, rollback does not require memory-file migration.
- If a sidecar causes issues, delete `*.phi.json`; the plugin should rebuild or operate without it.
- If draft skills are unwanted, remove the generated draft files; no installed skills are changed.
