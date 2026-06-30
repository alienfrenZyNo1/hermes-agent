# Phi Memory plugin

`phi-memory` is an optional Hermes plugin/add-on that provides golden-ratio memory governance for the built-in `MEMORY.md` and `USER.md` files.

It is **not** a memory provider backend. It does not replace built-in memory storage and it does not implement `plugins/memory/<provider>`. Instead, it layers review, scoring, recall, CLI/slash commands, a model tool, and optional deterministic write governance over the existing files.

## Curl install

For an existing Hermes install, install Phi Memory into the current user's Hermes home with:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash
```

Replace an existing install/update the copied plugin files:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --force
```

Install into a non-default Hermes home:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --hermes-home /path/to/.hermes
```

The installer:

1. Requires an existing `hermes` CLI on `PATH`.
2. Copies only `plugins/phi-memory/` into `~/.hermes/plugins/phi-memory/`.
3. Enables the plugin with `hermes plugins enable phi-memory` unless `--no-enable` is passed.
4. Runs a dry-run smoke check: `hermes phi-memory status --target memory`.
5. Never edits `MEMORY.md` or `USER.md`.

## Enable / disable

```bash
hermes plugins enable phi-memory
hermes plugins disable phi-memory
```

The plugin can also be copied manually to:

```text
~/.hermes/plugins/phi-memory/
```

and enabled with the same `hermes plugins enable phi-memory` command.

## Config

Preferred plugin config:

```yaml
phi_memory:
  enabled: true
  safe_apply_enabled: true
  auto_safe_cleanup_on_write_pressure: false
  auto_safe_cleanup_threshold: 0.95
  default_dry_run: true
  metadata_sidecar_enabled: true
  metadata_sidecar_version: 1
  fibonacci_review_enabled: true
  fibonacci_review_intervals: [1, 2, 3, 5, 8, 13]
  recall_session_fallback_enabled: true
  recall_active_confidence_threshold: 0.45
  skill_candidate_detection_enabled: true
  skill_candidate_draft_enabled: true
  semantic_compression_enabled: true
  semantic_compression_apply_enabled: false
  dashboard_enabled: true
```

For compatibility, existing `memory.phi` config is still read. When both locations are explicitly configured, top-level `phi_memory` values take precedence.

## CLI

```bash
hermes phi-memory status --target memory
hermes phi-memory review --target user
hermes phi-memory compress --target memory
hermes phi-memory compress --target memory --apply-safe
hermes phi-memory explain "User prefers concise deployment summaries" --target user
hermes phi-memory recall "deployment coolify" --target memory
hermes phi-memory recall "deployment coolify" --target memory --include-session
hermes phi-memory dashboard --target memory
hermes phi-memory meta status --target memory
hermes phi-memory meta rebuild --target memory
hermes phi-memory review-due --target memory
hermes phi-memory mark-reviewed <memory_id> --target memory
hermes phi-memory schedule --target memory
hermes phi-memory skills candidates --target memory
hermes phi-memory skills draft <candidate_id> --target memory
hermes phi-memory compress --target memory --semantic --budget 1400
```

## Slash command

```text
/phi-memory status
/phi-memory review --target user
/phi-memory compress --target memory
/phi-memory compress --target memory --apply-safe
/phi-memory explain User prefers concise deployment summaries --target user
/phi-memory recall deployment coolify --target memory
/phi-memory recall deployment coolify --target memory --include-session
/phi-memory dashboard --target memory
/phi-memory meta status --target memory
/phi-memory review-due --target memory
/phi-memory schedule --target memory
/phi-memory skills candidates --target memory
/phi-memory compress --target memory --semantic --budget 1400
```

A legacy `/memory phi ...` shim may dispatch to this plugin when enabled.

## Tool

The plugin registers the model tool `phi_memory` with actions:

- `status`
- `review`
- `compress`
- `explain`
- `recall`
- `dashboard`
- `meta_status`, `meta_rebuild`, `meta_validate`
- `review_due`, `schedule`
- `skill_candidates`

`compress` remains dry-run unless `apply_safe: true` is explicitly passed.

## Safety model

Default compression is proposal-only. It never mutates `MEMORY.md` or `USER.md`.

`--apply-safe` is the only automatic cleanup mode. It is deterministic and may only:

- remove exact duplicates
- remove normalized duplicates
- trim whitespace
- remove empty or obviously broken fragments
- redact obvious sensitive values and `.secrets` paths

It does **not** use an LLM, perform semantic rewriting, merge unrelated memories, or delete unique project facts. Before writing, it creates a timestamped backup beside the original file:

```text
MEMORY.md.bak.<timestamp>
USER.md.bak.<timestamp>
```

If backup creation fails or cleanup would produce an empty/invalid file, it refuses to write.

## Safe cleanup vs semantic compression

- **Semantic compression**: review proposal only; shows what could be summarized or archived by a human/operator.
- **Safe cleanup**: deterministic apply mode for duplicates, whitespace, broken fragments, and redaction only.

## Memory-write governance

When enabled, the plugin registers a generic `pre_memory_write` hook. It can reject obvious sensitive memory candidates, skip normalized duplicates, and optionally perform one safe cleanup retry when a normal memory add hits emergency pressure.

Automatic-on-write cleanup is disabled by default:

```yaml
phi_memory:
  auto_safe_cleanup_on_write_pressure: false
```
