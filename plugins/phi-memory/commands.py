"""CLI and slash command handlers for the Phi Memory plugin."""

from __future__ import annotations

import argparse

from . import core
from .memory_adapter import get_store


def handle_slash(raw_args: str) -> str:
    try:
        import shlex
        args = shlex.split(raw_args or "")
    except ValueError:
        args = (raw_args or "").split()
    return core.handle_phi_memory_args(get_store(), args)


def register_cli(subparser: argparse.ArgumentParser) -> None:
    sub = subparser.add_subparsers(dest="phi_memory_command")
    for name in ("status", "review", "compress"):
        p = sub.add_parser(name, help=f"Phi Memory {name}")
        p.add_argument("--target", choices=["memory", "user"], default="memory")
        if name == "compress":
            p.add_argument("--apply-safe", action="store_true", help="Apply deterministic safe cleanup only, with backup")
        p.add_argument("--json", action="store_true", help="Print raw JSON report")
    explain = sub.add_parser("explain", help="Explain how Phi Memory would score text")
    explain.add_argument("text", nargs="+", help="Memory text to explain")
    explain.add_argument("--target", choices=["memory", "user"], default="memory")
    explain.add_argument("--json", action="store_true")
    recall = sub.add_parser("recall", help="Search active memory with Phi scoring")
    recall.add_argument("query", nargs="+", help="Recall query")
    recall.add_argument("--target", choices=["memory", "user"], default="memory")
    recall.add_argument("--json", action="store_true")


def handle_cli(args) -> None:
    import json
    store = get_store()
    command = getattr(args, "phi_memory_command", None) or "status"
    target = getattr(args, "target", "memory")
    as_json = bool(getattr(args, "json", False))
    if command in {"status", "review", "compress"}:
        if command == "compress" and bool(getattr(args, "apply_safe", False)):
            report = core.apply_safe_cleanup(store, target=target)
            print(json.dumps(report, indent=2, ensure_ascii=False) if as_json else core.format_safe_cleanup_report(report))
            return
        report = core.review_store(store, target=target, dry_run=True)
        if command == "compress":
            report["mode"] = "compress"
            report["note"] = "Compression is currently proposal-only; no memory files were changed."
        print(json.dumps(report, indent=2, ensure_ascii=False) if as_json else core.format_phi_report(report))
        return
    if command == "explain":
        text = " ".join(getattr(args, "text", []) or [])
        report = core.explain_text(text, target=target, existing_entries=store._entries_for(target))
        if as_json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            c = report["candidate"]
            print(f"Phi score: {c['phi_score']:.3f} — tier={c['tier']} — save={c['should_save']}\n{c['reason']}")
        return
    if command == "recall":
        query = " ".join(getattr(args, "query", []) or [])
        report = core.recall(store, query, target=target)
        if as_json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            lines = [f"Phi recall: {report['query']}"]
            for hit in report.get("hits", []):
                lines.append(f"- [{hit['score']:.3f}] {hit['text']}")
            if not report.get("hits"):
                lines.append("No active memory hit. Use session_search for archive recall.")
            print("\n".join(lines))
