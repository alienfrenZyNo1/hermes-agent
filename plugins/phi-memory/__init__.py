"""Phi Memory plugin registration."""

from __future__ import annotations

from . import commands, dashboard, hooks, metadata, review, schemas, semantic, session_recall, skills, tools


def _host_supports_hook(hook_name: str) -> bool:
    """Return True when this Hermes version advertises *hook_name*.

    ``pre_memory_write`` was added after the first Phi Memory plugin builds.
    Older Hermes installs still load and use the CLI/tool surfaces, but they log
    a warning if a plugin registers an unknown hook. Feature-detecting keeps the
    install clean while preserving write governance on newer hosts.
    """
    try:
        from hermes_cli.plugins import VALID_HOOKS
    except Exception:
        return False
    return hook_name in VALID_HOOKS


def register(ctx) -> None:
    ctx.register_tool(
        name="phi_memory",
        toolset="phi_memory",
        schema=schemas.PHI_MEMORY_SCHEMA,
        handler=tools.handle_phi_memory,
        description="Phi Memory governance over built-in MEMORY.md/USER.md",
        emoji="φ",
    )
    ctx.register_command(
        "phi-memory",
        commands.handle_slash,
        description="Phi Memory status/review/compress/explain/recall",
        args_hint="status|review|compress|explain|recall [--target memory|user]",
    )
    ctx.register_cli_command(
        name="phi-memory",
        help="Phi Memory governance for built-in memory files",
        description="Inspect and safely clean MEMORY.md/USER.md with Phi Memory governance.",
        setup_fn=commands.register_cli,
        handler_fn=commands.handle_cli,
    )
    if _host_supports_hook("pre_memory_write"):
        ctx.register_hook("pre_memory_write", hooks.on_pre_memory_write)
