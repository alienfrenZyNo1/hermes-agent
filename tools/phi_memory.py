"""Compatibility shim for the optional phi-memory plugin.

Phi Memory logic lives in ``plugins/phi-memory``.  This module remains only so
older ``/memory phi`` and ``hermes memory phi`` compatibility paths can dispatch
to the plugin when it is enabled.  It deliberately contains no Phi Memory
business logic.
"""

from __future__ import annotations

import sys
from typing import Any, Sequence

_DISABLED = (
    "Phi Memory is provided by the optional phi-memory plugin. "
    "Enable it with: hermes plugins enable phi-memory"
)


def _core():
    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:
        pass
    return sys.modules.get("hermes_plugins.phi_memory.core")


def plugin_available() -> bool:
    return _core() is not None


def phi_enabled() -> bool:
    core = _core()
    return bool(core and core.phi_enabled())


def handle_phi_memory_args(store: Any, args: Sequence[str]) -> str:
    core = _core()
    if core is None:
        return _DISABLED
    return core.handle_phi_memory_args(store, args)


def __getattr__(name: str):
    core = _core()
    if core is None:
        raise AttributeError(f"Phi Memory plugin is not enabled; missing {name!r}")
    return getattr(core, name)
