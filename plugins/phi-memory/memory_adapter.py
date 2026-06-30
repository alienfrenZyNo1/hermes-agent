"""Adapter over Hermes' built-in MEMORY.md / USER.md storage."""

from __future__ import annotations

from typing import Any

from tools.memory_tool import MemoryStore


def _configured_limits() -> tuple[int, int]:
    """Return configured memory/user char limits with safe defaults.

    Newer Hermes exposes ``tools.memory_tool.load_on_disk_store()`` for this.
    Older installs do not, so the plugin carries the small compatibility shim
    here instead of failing import during plugin discovery.
    """
    memory_char_limit = 2200
    user_char_limit = 1375
    try:
        from hermes_cli.config import load_config

        mem_cfg: Any = (load_config() or {}).get("memory", {}) or {}
        memory_char_limit = int(mem_cfg.get("memory_char_limit", memory_char_limit))
        user_char_limit = int(mem_cfg.get("user_char_limit", user_char_limit))
    except Exception:
        pass
    return memory_char_limit, user_char_limit


def get_store() -> MemoryStore:
    """Return a MemoryStore loaded from the active profile's built-in files."""
    try:
        from tools.memory_tool import load_on_disk_store
    except ImportError:
        load_on_disk_store = None

    if load_on_disk_store is not None:
        return load_on_disk_store()

    memory_char_limit, user_char_limit = _configured_limits()
    store = MemoryStore(
        memory_char_limit=memory_char_limit,
        user_char_limit=user_char_limit,
    )
    store.load_from_disk()
    return store
