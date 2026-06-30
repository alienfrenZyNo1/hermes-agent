# Phi Memory for Hermes

Phi Memory is an optional Hermes plugin that adds **memory governance** for the
built-in `MEMORY.md` and `USER.md` files.

It helps keep long-term agent memory compact, durable, and high-signal by
reviewing memory pressure, scoring entries, detecting stale/noisy memories,
proposing compression, maintaining sidecar metadata, and surfacing candidates
that should become reusable skills.

Phi Memory is **not** a replacement memory backend, vector database, or
`plugins/memory/<provider>` implementation. It sits above Hermes' normal memory
files as a governance/hygiene layer.

## What it does

- Reviews `MEMORY.md` and `USER.md` usage against phi-inspired thresholds.
- Suggests whether entries should be kept, compressed, archived, or reviewed.
- Provides dry-run compression reports by default.
- Supports deterministic safe cleanup for duplicates, whitespace, broken
  fragments, and obvious secret redaction.
- Maintains optional metadata sidecars such as `MEMORY.md.phi.json` and
  `USER.md.phi.json`.
- Offers recall helpers with optional session-search fallback.
- Detects memory entries that look more like reusable procedures and should
  become skills.
- Registers a model-facing `phi_memory` tool and `/phi-memory` slash command.

## Install

### One-line curl install

For an existing Hermes install:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash
```

Replace/update an existing copied plugin install:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --force
```

Install into a non-default Hermes home:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --hermes-home /path/to/.hermes
```

Install without enabling immediately:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --no-enable
```

The installer:

1. Requires an existing `hermes` CLI on `PATH`.
2. Clones the configured Hermes fork/ref.
3. Copies only `plugins/phi-memory/` into `~/.hermes/plugins/phi-memory/`.
4. Enables the plugin with `hermes plugins enable phi-memory` unless
   `--no-enable` is passed.
5. Runs a dry-run smoke check: `hermes phi-memory status --target memory`.
6. Never edits `MEMORY.md` or `USER.md`.

### Manual install

You can also copy this directory manually:

```text
~/.hermes/plugins/phi-memory/
```

Then enable it:

```bash
hermes plugins enable phi-memory
```

For gateways or long-running Hermes sessions, restart the process after enabling
so the plugin is discovered.

## Quickstart

```bash
# Check memory pressure and proposed action
hermes phi-memory status --target memory
hermes phi-memory status --target user

# Review entries without changing files
hermes phi-memory review --target memory

# Proposal-only compression report
hermes phi-memory compress --target memory

# Explain whether a candidate belongs in memory
hermes phi-memory explain "User prefers concise deployment summaries" --target user

# Search active memory, optionally falling back to session history
hermes phi-memory recall "deployment coolify" --target memory
hermes phi-memory recall "deployment coolify" --target memory --include-session
```

## CLI reference

```bash
hermes phi-memory status --target memory
hermes phi-memory review --target user
hermes phi-memory compress --target memory
hermes phi-memory compress --target memory --apply-safe
hermes phi-memory compress --target memory --semantic --budget 1400
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

## Model tool

The plugin registers the model-facing tool `phi_memory` with actions:

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

## Configuration

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

For compatibility, existing `memory.phi` config is still read. When both
locations are explicitly configured, top-level `phi_memory` values take
precedence.

## Safety model

Default compression is proposal-only. It never mutates `MEMORY.md` or `USER.md`.

`--apply-safe` is the only automatic cleanup mode. It is deterministic and may
only:

- remove exact duplicates
- remove normalized duplicates
- trim whitespace
- remove empty or obviously broken fragments
- redact obvious sensitive values and `.secrets` paths

It does **not** use an LLM, perform semantic rewriting, merge unrelated
memories, or delete unique project facts. Before writing, it creates a
timestamped backup beside the original file:

```text
MEMORY.md.bak.<timestamp>
USER.md.bak.<timestamp>
```

If backup creation fails or cleanup would produce an empty/invalid file, it
refuses to write.

## Safe cleanup vs semantic compression

- **Semantic compression**: proposal only; shows what could be summarized or
  archived by a human/operator.
- **Safe cleanup**: deterministic apply mode for duplicates, whitespace, broken
  fragments, and redaction only.

## Memory-write governance

When enabled, the plugin registers a generic `pre_memory_write` hook. It can
reject obvious sensitive memory candidates, skip normalized duplicates, and
optionally perform one safe cleanup retry when a normal memory add hits emergency
pressure.

Automatic-on-write cleanup is disabled by default:

```yaml
phi_memory:
  auto_safe_cleanup_on_write_pressure: false
```

## Update

If installed with the curl installer, rerun it with `--force`:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --force
```

If installed as a git plugin checkout through Hermes' plugin manager, you can
also use:

```bash
hermes plugins update phi-memory
```

## Disable or uninstall

Disable without deleting files:

```bash
hermes plugins disable phi-memory
```

Remove the copied plugin directory:

```bash
rm -rf ~/.hermes/plugins/phi-memory
```

This does not delete or edit your memory files.

## Troubleshooting

### `Plugin 'phi-memory' registered unknown hook 'pre_memory_write'`

Update Phi Memory with the latest installer:

```bash
curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash -s -- --force
```

Older Hermes versions do not advertise the `pre_memory_write` hook. Recent Phi
Memory builds feature-detect that hook and skip registering it when unsupported,
so the plugin still loads cleanly. On those older hosts, the CLI, slash command,
and `phi_memory` tool still work; only automatic memory-write governance is
unavailable until Hermes itself is updated.

### `cannot import name 'load_on_disk_store'`

Update Phi Memory with the latest installer. Newer plugin builds include a
compatibility fallback for Hermes versions that do not expose
`tools.memory_tool.load_on_disk_store()`.

### `hermes phi-memory` is not found

Enable the plugin and restart any long-running Hermes gateway/session:

```bash
hermes plugins enable phi-memory
hermes gateway restart
```

### The installer cannot find `hermes`

Install Hermes first and make sure the `hermes` command is on `PATH`:

```bash
hermes --help
```

### Smoke check passes but the agent cannot use the tool

Restart the active Hermes process. Tool registration happens when a session or
gateway loads plugins.

## Development

From the Hermes repo:

```bash
bash -n scripts/install-phi-memory.sh
python -m py_compile plugins/phi-memory/*.py
```

To test the installer without touching your real Hermes home:

```bash
tmp=$(mktemp -d)
./scripts/install-phi-memory.sh --source-dir plugins/phi-memory --hermes-home "$tmp" --force
HERMES_HOME="$tmp" hermes phi-memory status --target memory
rm -rf "$tmp"
```
