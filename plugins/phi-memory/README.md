# Phi Memory plugin

`phi-memory` is an optional Hermes plugin/add-on that provides golden-ratio memory governance for the built-in `MEMORY.md` and `USER.md` files.

It is **not** a memory provider backend. It does not replace built-in memory storage and it does not implement `plugins/memory/<provider>`. Instead, it layers review, scoring, recall, CLI/slash commands, a model tool, and optional deterministic write governance over the existing files.

## Enable / disable

```bash
hermes plugins enable phi-memory
hermes plugins disable phi-memory
```

The plugin can also be copied to:

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
```

For compatibility, existing `memory.phi` config is still read. Top-level `phi_memory` values take precedence.

## CLI

```bash
hermes phi-memory status --target memory
hermes phi-memory review --target user
hermes phi-memory compress --target memory
hermes phi-memory compress --target memory --apply-safe
hermes phi-memory explain "User prefers concise deployment summaries" --target user
hermes phi-memory recall "deployment coolify" --target memory
```

## Slash command

```text
/phi-memory status
/phi-memory review --target user
/phi-memory compress --target memory
/phi-memory compress --target memory --apply-safe
/phi-memory explain User prefers concise deployment summaries --target user
/phi-memory recall deployment coolify --target memory
```

A legacy `/memory phi ...` shim may dispatch to this plugin when enabled.

## Tool

The plugin registers the model tool `phi_memory` with actions:

- `status`
- `review`
- `compress`
- `explain`
- `recall`

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
