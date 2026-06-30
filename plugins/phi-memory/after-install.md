# Phi Memory installed

Phi Memory has been copied into your Hermes plugins directory.

Enable it if the installer did not already do so:

```bash
hermes plugins enable phi-memory
```

Smoke test:

```bash
hermes phi-memory status --target memory
hermes phi-memory status --target user
```

For Telegram/Discord/Slack gateways or other long-running Hermes sessions, restart the gateway/session so the newly enabled plugin is discovered.

Phi Memory compression is proposal-only by default. It does **not** modify `MEMORY.md` or `USER.md` unless you explicitly run the deterministic safe cleanup mode, for example:

```bash
hermes phi-memory compress --target memory --apply-safe
```
