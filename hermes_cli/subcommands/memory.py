"""``hermes memory`` subcommand parser.

Extracted from ``hermes_cli/main.py:main()`` (god-file Phase 2 follow-up).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_memory_parser(subparsers, *, cmd_memory: Callable) -> None:
    """Attach the ``memory`` subcommand to ``subparsers``."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Configure external memory provider",
        description=(
            "Set up and manage external memory provider plugins.\n\n"
            "Available providers: honcho, openviking, mem0, hindsight,\n"
            "holographic, retaindb, byterover.\n\n"
            "Only one external provider can be active at a time.\n"
            "Built-in memory (MEMORY.md/USER.md) is always active."
        ),
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    _setup_parser = memory_sub.add_parser(
        "setup", help="Interactive provider selection and configuration"
    )
    _setup_parser.add_argument(
        "provider",
        nargs="?",
        default=None,
        help="Provider to configure directly (e.g. honcho), skipping the picker",
    )
    memory_sub.add_parser("status", help="Show current memory provider config")
    phi_parser = memory_sub.add_parser(
        "phi",
        help="Inspect Phi Memory golden-ratio governance",
        description="Review built-in memory with Phi Memory scoring. Review/compress default to dry-run.",
    )
    phi_sub = phi_parser.add_subparsers(dest="phi_command")
    for name in ("status", "review", "compress"):
        p = phi_sub.add_parser(name, help=f"Phi Memory {name}")
        p.add_argument("--target", choices=["memory", "user"], default="memory")
        if name in {"review", "compress"}:
            p.add_argument("--apply", action="store_true", help="Reserved for future mutating compaction; current implementation remains safe/dry-run")
            p.add_argument("--json", action="store_true", help="Print raw JSON report")
    explain = phi_sub.add_parser("explain", help="Explain how Phi Memory would score text")
    explain.add_argument("text", nargs="+", help="Memory text to explain")
    explain.add_argument("--target", choices=["memory", "user"], default="memory")
    explain.add_argument("--json", action="store_true", help="Print raw JSON report")
    recall = phi_sub.add_parser("recall", help="Search active memory before falling back to session_search manually")
    recall.add_argument("query", nargs="+", help="Recall query")
    recall.add_argument("--target", choices=["memory", "user"], default="memory")
    recall.add_argument("--json", action="store_true", help="Print raw JSON report")
    memory_sub.add_parser("off", help="Disable external provider (built-in only)")
    _reset_parser = memory_sub.add_parser(
        "reset",
        help="Erase all built-in memory (MEMORY.md and USER.md)",
    )
    _reset_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    _reset_parser.add_argument(
        "--target",
        choices=["all", "memory", "user"],
        default="all",
        help="Which store to reset: 'all' (default), 'memory', or 'user'",
    )
    memory_parser.set_defaults(func=cmd_memory)
