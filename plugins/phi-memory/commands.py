"""CLI and slash command handlers for the Phi Memory plugin."""

from __future__ import annotations

import argparse
import json

from . import core, dashboard as dashboard_mod, metadata, review, semantic, session_recall, skills
from .memory_adapter import get_store


def _json_or_text(report, formatter, as_json: bool) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) if as_json else formatter(report)


def _format_simple(report: dict) -> str:
    if not report.get("success", True):
        return report.get("error", "Phi Memory command failed.")
    return json.dumps(report, indent=2, ensure_ascii=False)


def _format_meta(report: dict) -> str:
    if not report.get("success", True):
        return report.get("error", "Phi Memory metadata command failed.")
    parts = [f"Phi Memory metadata {report.get('target', '')}: {report.get('status', 'ok')}"]
    if "valid" in report:
        parts.append(f"valid={report['valid']}")
    if report.get("path"):
        parts.append(f"path={report['path']}")
    if report.get("entries") is not None:
        parts.append(f"entries={report['entries']}")
    if report.get("backup_path"):
        parts.append(f"backup={report['backup_path']}")
    if report.get("error"):
        parts.append(f"error={report['error']}")
    return "\n".join(parts)


def _format_due(report: dict) -> str:
    lines = [f"Phi Memory review due ({report.get('target')}) — {report.get('count', 0)}"]
    for item in report.get("due", []):
        lines.append(
            f"- {item['memory_id']} [{item['current_score']:.3f}] {item['suggested_action']} — {item['why_due']} :: {item['safe_preview']}"
        )
    return "\n".join(lines)


def _format_schedule(report: dict) -> str:
    lines = [f"Phi Memory schedule ({report.get('target')}) — {report.get('count', 0)}"]
    for item in report.get("schedule", []):
        lines.append(
            f"- {item['memory_id']} next={item['next_review_after_interactions']} idx={item['review_interval_index']} access={item['access_count']} review={item['review_count']} :: {item['safe_preview']}"
        )
    return "\n".join(lines)


def _format_recall(report: dict) -> str:
    lines = [f"Phi recall: {report.get('query', '')}"]
    if report.get("session_error"):
        lines.append(report["session_error"])
    for hit in report.get("hits", []):
        lines.append(f"- {hit.get('source')} [{float(hit.get('score', 0)):.3f}] {hit.get('text')}")
    if not report.get("hits"):
        lines.append("No active or session archive hits found.")
    return "\n".join(lines)


def _format_candidates(report: dict) -> str:
    lines = [f"Phi Memory skill candidates ({report.get('target')}) — {report.get('count', 0)}"]
    for item in report.get("candidates", []):
        lines.append(f"- {item['candidate_id']} [{item['score']}] {item['suggested_skill_name']} :: {item['safe_preview']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phi-memory", add_help=True)
    register_cli(parser)
    return parser


def handle_slash(raw_args: str) -> str:
    try:
        import shlex
        argv = shlex.split(raw_args or "")
    except ValueError:
        argv = (raw_args or "").split()
    parser = build_parser()
    try:
        args = parser.parse_args(argv or ["status"])
    except SystemExit:
        return "Invalid /phi-memory command. Use: status, review, compress, dashboard, meta, review-due, schedule, recall, skills."
    return execute(args)


def register_cli(subparser: argparse.ArgumentParser) -> None:
    sub = subparser.add_subparsers(dest="phi_memory_command")
    for name in ("status", "review"):
        p = sub.add_parser(name, help=f"Phi Memory {name}")
        p.add_argument("--target", choices=["memory", "user"], default="memory")
        p.add_argument("--json", action="store_true", help="Print raw JSON report")
    compress = sub.add_parser("compress", help="Phi Memory compress")
    compress.add_argument("--target", choices=["memory", "user"], default="memory")
    compress.add_argument("--apply-safe", action="store_true", help="Apply deterministic safe cleanup only, with backup")
    compress.add_argument("--semantic", action="store_true", help="Generate semantic compression diff")
    compress.add_argument("--apply-semantic", action="store_true", help="Apply opt-in semantic compression when phi_memory.semantic_compression_apply_enabled=true")
    compress.add_argument("--budget", type=int, default=None)
    compress.add_argument("--json", action="store_true", help="Print raw JSON report")

    explain = sub.add_parser("explain", help="Explain how Phi Memory would score text")
    explain.add_argument("text", nargs="+", help="Memory text to explain")
    explain.add_argument("--target", choices=["memory", "user"], default="memory")
    explain.add_argument("--json", action="store_true")

    recall = sub.add_parser("recall", help="Search active memory with optional session fallback")
    recall.add_argument("query", nargs="+", help="Recall query")
    recall.add_argument("--target", choices=["memory", "user"], default="memory")
    recall.add_argument("--include-session", action="store_true")
    recall.add_argument("--active-only", action="store_true")
    recall.add_argument("--json", action="store_true")

    dashboard = sub.add_parser("dashboard", help="Show Phi Memory health dashboard")
    dashboard.add_argument("--target", choices=["memory", "user"], default=None)
    dashboard.add_argument("--json", action="store_true")

    meta = sub.add_parser("meta", help="Manage Phi Memory metadata sidecar")
    meta_sub = meta.add_subparsers(dest="meta_command")
    for name in ("status", "rebuild", "validate"):
        p = meta_sub.add_parser(name)
        p.add_argument("--target", choices=["memory", "user"], default="memory")
        p.add_argument("--json", action="store_true")

    due = sub.add_parser("review-due", help="Show memories due for Fibonacci review")
    due.add_argument("--target", choices=["memory", "user"], default="memory")
    due.add_argument("--json", action="store_true")

    mark = sub.add_parser("mark-reviewed", help="Mark a memory reviewed and advance schedule")
    mark.add_argument("memory_id")
    mark.add_argument("--target", choices=["memory", "user"], default="memory")
    mark.add_argument("--useful", action="store_true", default=True)
    mark.add_argument("--contradicted", action="store_true")
    mark.add_argument("--json", action="store_true")

    schedule = sub.add_parser("schedule", help="Show Fibonacci review schedule")
    schedule.add_argument("--target", choices=["memory", "user"], default="memory")
    schedule.add_argument("--json", action="store_true")

    skills_p = sub.add_parser("skills", help="Skill-candidate handoff")
    skills_sub = skills_p.add_subparsers(dest="skills_command")
    cand = skills_sub.add_parser("candidates")
    cand.add_argument("--target", choices=["memory", "user"], default="memory")
    cand.add_argument("--json", action="store_true")
    draft = skills_sub.add_parser("draft")
    draft.add_argument("candidate_id")
    draft.add_argument("--target", choices=["memory", "user"], default="memory")
    draft.add_argument("--write-file", action="store_true", default=True)
    draft.add_argument("--json", action="store_true")
    dismiss = skills_sub.add_parser("dismiss")
    dismiss.add_argument("candidate_id")
    dismiss.add_argument("--target", choices=["memory", "user"], default="memory")
    dismiss.add_argument("--json", action="store_true")


def execute(args) -> str:
    store = get_store()
    command = getattr(args, "phi_memory_command", None) or "status"
    target = getattr(args, "target", "memory")
    as_json = bool(getattr(args, "json", False))
    if command in {"status", "review"}:
        return _json_or_text(core.review_store(store, target=target, dry_run=True), core.format_phi_report, as_json)
    if command == "compress":
        if bool(getattr(args, "apply_semantic", False)):
            return _json_or_text(semantic.apply_semantic_compression(store, target, budget=getattr(args, "budget", None)), semantic.format_semantic_proposal, as_json)
        if bool(getattr(args, "semantic", False)):
            return _json_or_text(semantic.semantic_compression_proposal(store, target, budget=getattr(args, "budget", None)), semantic.format_semantic_proposal, as_json)
        if bool(getattr(args, "apply_safe", False)):
            return _json_or_text(core.apply_safe_cleanup(store, target=target), core.format_safe_cleanup_report, as_json)
        report = core.review_store(store, target=target, dry_run=True)
        report["mode"] = "compress"
        report["note"] = "Compression is currently proposal-only; no memory files were changed."
        return _json_or_text(report, core.format_phi_report, as_json)
    if command == "explain":
        report = core.explain_text(" ".join(getattr(args, "text", []) or []), target=target, existing_entries=store._entries_for(target))
        if as_json:
            return json.dumps(report, indent=2, ensure_ascii=False)
        c = report["candidate"]
        return f"Phi score: {c['phi_score']:.3f} — tier={c['tier']} — save={c['should_save']}\n{c['reason']}"
    if command == "recall":
        report = session_recall.recall_with_fallback(store, " ".join(getattr(args, "query", []) or []), target=target, include_session=getattr(args, "include_session", False), active_only=getattr(args, "active_only", False))
        return _json_or_text(report, _format_recall, as_json)
    if command == "dashboard":
        report = dashboard_mod.dashboard(store, target=target)
        return _json_or_text(report, dashboard_mod.format_dashboard, as_json)
    if command == "meta":
        meta_command = getattr(args, "meta_command", None) or "status"
        if meta_command == "rebuild":
            report = metadata.rebuild_sidecar(store, target)
            report["target"] = target
            report["status"] = "ok"
        elif meta_command == "validate":
            report = metadata.validate_sidecar(store, target)
        else:
            report = metadata.sidecar_status(store, target)
        return _json_or_text(report, _format_meta, as_json)
    if command == "review-due":
        return _json_or_text(review.review_due(store, target), _format_due, as_json)
    if command == "mark-reviewed":
        return _json_or_text(review.mark_reviewed(store, target, getattr(args, "memory_id"), useful=getattr(args, "useful", True), contradicted=getattr(args, "contradicted", False)), _format_simple, as_json)
    if command == "schedule":
        return _json_or_text(review.schedule(store, target), _format_schedule, as_json)
    if command == "skills":
        skills_command = getattr(args, "skills_command", None) or "candidates"
        if skills_command == "draft":
            report = skills.draft_skill(store, target, getattr(args, "candidate_id"), write_file=getattr(args, "write_file", True))
            return _json_or_text(report, _format_simple, as_json)
        if skills_command == "dismiss":
            report = skills.dismiss_candidate(store, target, getattr(args, "candidate_id"))
            return _json_or_text(report, _format_simple, as_json)
        return _json_or_text(skills.find_skill_candidates(store, target), _format_candidates, as_json)
    return "Unknown Phi Memory command."


def handle_cli(args) -> None:
    print(execute(args))
