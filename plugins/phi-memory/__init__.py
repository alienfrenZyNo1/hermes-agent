"""Phi Memory plugin registration."""

from __future__ import annotations

from . import commands, hooks, schemas, tools


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
    ctx.register_hook("pre_memory_write", hooks.on_pre_memory_write)
