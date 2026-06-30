"""Compatibility entrypoint for plugin packaging docs.

Hermes loads directory plugins via ``__init__.py``. This module exists because
the phi-memory plugin package layout also documents an ``init.py`` entrypoint;
keep all registration logic in ``__init__.py``.
"""

from . import register

__all__ = ["register"]
