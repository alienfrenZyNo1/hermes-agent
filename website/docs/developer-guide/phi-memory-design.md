---
title: "Phi Memory design note"
description: "Design notes for Phi Memory golden-ratio memory governance"
---

# Phi Memory design note

## Current memory architecture
- Built-in memory is `tools/memory_tool.py`: two profile-scoped, §-delimited files under `~/.hermes/memories/`: `MEMORY.md` and `USER.md`.
- `MemoryStore` loads a frozen snapshot at session start, injects it into the system prompt, and keeps live file state for writes. This preserves prompt caching.
- The `memory` tool supports `add`, `replace`, `remove`, plus atomic batch operations. It blocks strict prompt-injection/exfiltration patterns before writes.
- External memory providers are optional plugins coordinated by `agent/memory_manager.py`; only one external provider is active at a time.
- Session history/search already lives outside active memory and is the right archive tier for old details.

## Implemented architecture
Phi Memory is packaged as the optional `phi-memory` plugin, not a new memory
backend:
- `plugins/phi-memory/core.py` holds named golden-ratio constants, candidate schema, scoring, pressure analysis, dry-run review/compression plans, deterministic safe cleanup, and recall over active memory entries.
- Existing `MemoryStore` remains the storage layer. The plugin consumes a small generic `pre_memory_write` hook to govern normal writes when enabled, while preserving current file format/backward compatibility.
- CLI surface is `hermes phi-memory status|review|compress|explain|recall`. Legacy `hermes memory phi ...` dispatches to the plugin as a thin compatibility shim when it is enabled.
- Slash surface is `/phi-memory ...`. Legacy `/memory phi ...` dispatches to the plugin as a thin compatibility shim when it is enabled.
- Config uses `phi_memory` plugin values and still reads legacy `memory.phi` overrides for compatibility.

## Affected files
- `plugins/phi-memory/` — optional plugin package containing governance logic, tool/CLI/slash surfaces, hooks, adapter, README, and tests.
- `tools/phi_memory.py` — compatibility shim only; no Phi business logic.
- `tools/memory_tool.py` — generic `pre_memory_write`/`post_memory_write` hook points around `MemoryStore.add`.
- `hermes_cli/plugins.py` — generic memory hook names.
- `hermes_cli/main.py`, `hermes_cli/cli_commands_mixin.py`, `gateway/slash_commands.py` — legacy `memory phi` compatibility shims.
- `website/docs/user-guide/features/memory.md`, `website/docs/reference/slash-commands.md`, this design note — plugin docs.

## Risks
- Over-aggressive automatic compression could destroy user data. Mitigation: semantic compression remains proposal-only; `--apply-safe` cannot rewrite/merge unique facts and only applies deterministic cleanup after creating a backup.
- Prompt-cache breakage if active memory mutates mid-session. Mitigation: keep frozen snapshot behavior unchanged.
- Tool schema bloat. Mitigation: no new model tool; use CLI/governance helpers and existing `memory` tool.
- Heuristic scoring ambiguity. Mitigation: deterministic, testable scoring with explicit reason strings and conservative save/reject decisions.

## Test plan
- Constants and threshold math.
- Phi scoring and promotion/short-term/remove tiers.
- Explicit remember boosts but does not bypass secret rejection.
- Exact/normalized duplicate detection.
- Contradictory replacement proposal.
- Capacity pressure bands: healthy, review, consolidate, emergency.
- Dry-run review/compress does not mutate `MEMORY.md`/`USER.md`.
- `compress --apply-safe` removes duplicates/empty fragments, redacts obvious secrets without echoing them, creates backups, reports pressure, and preserves unique project facts/protected memory types.
- Optional on-write safe cleanup is disabled by default and retries once only when explicitly enabled.
- CLI `phi-memory ...` commands and legacy `memory phi ...` shims operate on temp `HERMES_HOME`.
