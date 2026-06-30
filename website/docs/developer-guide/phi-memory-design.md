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

## Proposed change
Add a small governance layer, not a new memory backend:
- New `tools/phi_memory.py` holds named golden-ratio constants, candidate schema, scoring, pressure analysis, dry-run review/compression plans, and recall over active memory entries.
- Existing `MemoryStore` remains the storage layer. Phi Memory evaluates writes and adds pressure/explanation details only where useful, while preserving current file format/backward compatibility.
- CLI surface extends `hermes memory` with `phi status|review|compress|explain|recall` for operator inspection. `review` and `compress` default to dry-run.
- Config adds `memory.phi` values so ratios/thresholds are named and configurable instead of hardcoded throughout.

## Affected files
- `tools/phi_memory.py` — deterministic governance logic.
- `tools/memory_tool.py` — call Phi evaluation on adds; include Phi pressure in over-capacity errors while keeping normal success responses quiet.
- `hermes_cli/config.py` — default Phi config.
- `hermes_cli/subcommands/memory.py` and `hermes_cli/main.py` — CLI commands.
- `website/docs/user-guide/features/memory.md` — user-facing docs.
- `tests/tools/test_phi_memory.py` plus existing memory/CLI/gateway memory tests — coverage.

## Risks
- Over-aggressive automatic compression could destroy user data. Mitigation: first implementation only proposes compression by default; no mutation unless a future explicit apply path is added.
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
- CLI `memory phi ...` commands operate on temp `HERMES_HOME`.
