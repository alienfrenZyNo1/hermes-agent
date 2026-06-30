"""Adapter over Hermes' built-in MEMORY.md / USER.md storage."""

from __future__ import annotations

from tools.memory_tool import MemoryStore, load_on_disk_store


def get_store() -> MemoryStore:
    """Return a MemoryStore loaded from the active profile's built-in files."""
    return load_on_disk_store()
