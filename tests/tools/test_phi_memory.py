"""Tests for Phi Memory governance."""

import json

import pytest

from tools.memory_tool import MemoryStore, memory_tool
from tools.phi_memory import (
    PHI,
    PHI_HARD_WARNING,
    PHI_MAJOR,
    PHI_MINOR,
    apply_safe_cleanup,
    explain_text,
    handle_phi_memory_args,
    phi_config,
    pressure_level,
    recall,
    review_store,
    score_text,
)


def test_phi_constants():
    assert PHI == pytest.approx(1.61803398875)
    assert PHI_MAJOR == pytest.approx(0.61803398875)
    assert PHI_MINOR == pytest.approx(0.38196601125)
    assert PHI_HARD_WARNING == pytest.approx(PHI / 2)


def test_phi_scoring_thresholds_for_user_preference():
    candidate = score_text(
        "User prefers direct practical answers for engineering work",
        target="user",
        explicit_user_request=True,
    )
    assert candidate.phi_score >= PHI_MAJOR
    assert candidate.should_promote is True
    assert candidate.tier == "long_term"


def test_short_term_open_loop_stays_short_term():
    candidate = score_text(
        "We are currently refactoring the Telegram bot upload flow",
        target="memory",
    )
    assert PHI_MINOR <= candidate.phi_score < PHI_MAJOR
    assert candidate.tier == "short_term"


def test_explicit_remember_does_not_bypass_secret_rejection():
    candidate = score_text("Remember api_key='sk-abcdefghijklmnopqrstuvwx'", explicit_user_request=True)
    assert candidate.is_secret_or_sensitive is True
    assert candidate.should_save is False
    assert candidate.should_remove is True


def test_duplicate_handling_normalized():
    existing = ["User prefers direct practical answers"]
    candidate = score_text(" user   prefers DIRECT practical answers ", target="user", existing_entries=existing)
    assert candidate.should_save is False
    assert candidate.should_remove is True
    assert candidate.related_memory_ids == ["existing:0"]


def test_contradictory_memory_replacement_hint():
    existing = ["User prefers verbose answers for debugging"]
    candidate = score_text("User prefers concise answers for debugging", target="user", existing_entries=existing)
    assert candidate.supersedes_memory_ids == ["existing:0"]
    assert "supersede" in candidate.reason


def test_capacity_pressure_bands():
    assert pressure_level(617, 1000)["level"] == "healthy"
    assert pressure_level(618, 1000)["level"] == "review"
    assert pressure_level(810, 1000)["level"] == "consolidate"
    assert pressure_level(950, 1000)["level"] == "emergency"


def test_dry_run_review_does_not_mutate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    assert store.add("memory", "Project alpha uses FastAPI and PostgreSQL")["success"]
    before = (tmp_path / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    report = review_store(store, target="memory", dry_run=True)

    after = (tmp_path / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert before == after
    assert report["dry_run"] is True
    assert report["proposals"]


def test_recall_searches_active_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    store.add("memory", "Coolify deployment uses force rebuild queue API")

    report = recall(store, "coolify rebuild", target="memory")

    assert report["hits"]
    assert report["hits"][0]["source"] == "active:memory"
    assert "session_search" in report["archive_hint"]


def test_memory_tool_phi_rejects_secret_without_echoing_candidate_text(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    sensitive = "Remember token='abcdefghijklmnop'"

    result = json.loads(
        memory_tool(
            action="add",
            target="memory",
            content=sensitive,
            store=store,
        )
    )

    assert result["success"] is False
    assert "secret" in result["error"].lower() or "blocked" in result["error"].lower()
    assert sensitive not in json.dumps(result)


def test_explain_text_contains_reason():
    report = explain_text("User prefers concise replies", target="user")
    assert report["success"] is True
    assert report["candidate"]["reason"]
    assert "phi_score" in report["candidate"]


def test_slash_phi_handler_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    store.add("memory", "Project alpha uses FastAPI and PostgreSQL")

    out = handle_phi_memory_args(store, ["status", "--target", "memory"])

    assert "Phi Memory memory" in out
    assert "Project alpha" in out


def test_slash_phi_unquoted_text_and_target_parsing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    store.add("memory", "Coolify deployment uses force rebuild queue API")

    explain = handle_phi_memory_args(
        store,
        ["explain", "User", "prefers", "concise", "deployment", "summaries", "--target", "user"],
    )
    recall_out = handle_phi_memory_args(
        store,
        ["recall", "deployment", "coolify", "--target", "memory"],
    )

    assert "tier=" in explain
    assert "--target" not in explain
    assert "Coolify deployment" in recall_out
    assert "--target" not in recall_out


def test_slash_phi_invalid_target_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    out = handle_phi_memory_args(store, ["status", "--target", "banana"])

    assert "Invalid --target" in out


def test_phi_disabled_restores_quiet_add_response(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config_dir = tmp_path
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("memory:\n  phi:\n    enabled: false\n", encoding="utf-8")
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    result = json.loads(
        memory_tool(
            action="add",
            target="memory",
            content="Project beta uses Django",
            store=store,
        )
    )
    disabled_msg = handle_phi_memory_args(store, ["status"])

    assert result["success"] is True
    assert "phi" not in result
    assert "disabled" in disabled_msg.lower()


def _write_memory_file(tmp_path, target, entries):
    filename = "USER.md" if target == "user" else "MEMORY.md"
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / filename).write_text("\n§\n".join(entries), encoding="utf-8")
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    return store, mem_dir / filename


def test_compress_remains_dry_run_without_apply_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        " project   alpha uses FASTAPI ",
    ])
    before = path.read_text(encoding="utf-8")

    out = handle_phi_memory_args(store, ["compress", "--target", "memory"])
    apply_out = handle_phi_memory_args(store, ["compress", "--target", "memory", "--apply"])

    assert path.read_text(encoding="utf-8") == before
    assert "Dry run: True" in out
    assert "Dry run: True" in apply_out
    assert not list(path.parent.glob("MEMORY.md.bak.*"))


def test_apply_safe_removes_exact_and_normalized_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        "Project alpha uses FastAPI",
        " project   alpha uses FASTAPI ",
        "Project beta uses PostgreSQL",
    ])

    report = apply_safe_cleanup(store, target="memory")
    content = path.read_text(encoding="utf-8")

    assert report["success"] is True
    assert report["entries_removed"] == 2
    assert content.count("Project alpha uses FastAPI") == 1
    assert "Project beta uses PostgreSQL" in content
    assert report["backup_path"]
    assert path.parent.glob("MEMORY.md.bak.*")


def test_apply_safe_trims_whitespace_and_removes_empty_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "   Project alpha uses   FastAPI   ",
        "   ",
        "Project beta uses PostgreSQL",
    ])

    report = apply_safe_cleanup(store, target="memory")
    content = path.read_text(encoding="utf-8")

    assert report["entries_removed"] == 1
    assert report["applied"] is True
    assert "Project alpha uses FastAPI" in content
    assert "   Project" not in content
    assert "\n§\n   \n§\n" not in content


def test_apply_safe_removes_broken_fragment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        "...",
        "Project beta uses PostgreSQL",
    ])

    report = apply_safe_cleanup(store, target="memory")
    content = path.read_text(encoding="utf-8")

    assert report["entries_removed"] == 1
    assert "..." not in content
    assert "Project alpha uses FastAPI" in content


def test_apply_safe_redacts_suspected_secrets_without_echoing_them(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    sensitive_value = "«redacted:sk-…»"
    sensitive_path = "/home/lunafox/.secrets/service-account.json"
    store, path = _write_memory_file(tmp_path, "memory", [
        f"Project alpha token={sensitive_value} and key file {sensitive_path}",
        "Project beta uses PostgreSQL",
    ])

    dry_run = handle_phi_memory_args(store, ["compress", "--target", "memory"])
    report = apply_safe_cleanup(store, target="memory")
    content = path.read_text(encoding="utf-8")
    report_text = json.dumps(report)

    assert report["entries_redacted"] == 1
    assert sensitive_value not in dry_run
    assert sensitive_path not in dry_run
    assert sensitive_value not in content
    assert sensitive_path not in content
    assert sensitive_value not in report_text
    assert sensitive_path not in report_text
    assert "[REDACTED_SECRET]" in content
    assert "[REDACTED_SECRET_PATH]" in content


def test_apply_safe_reports_pressure_and_creates_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        " project   alpha uses FastAPI ",
    ])

    report = apply_safe_cleanup(store, target="memory")

    assert report["old_chars"] > report["new_chars"]
    assert "percent_before" in report
    assert "percent_after" in report
    assert report["backup_path"]
    assert (path.parent / report["backup_path"].split("/")[-1]).exists()
    assert "--- MEMORY.md before" in report["diff"]


def test_apply_safe_aborts_without_write_if_backup_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        " project   alpha uses FASTAPI ",
    ])
    before = path.read_text(encoding="utf-8")

    def fail_copy(*_args, **_kwargs):
        raise OSError("no backup")

    monkeypatch.setattr("tools.phi_memory.shutil.copy2", fail_copy)
    report = apply_safe_cleanup(store, target="memory")

    assert report["success"] is False
    assert report["applied"] is False
    assert "Backup creation failed" in report["error"]
    assert path.read_text(encoding="utf-8") == before


def test_apply_safe_disabled_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "memory:\n"
        "  phi:\n"
        "    safe_apply_enabled: false\n",
        encoding="utf-8",
    )
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha uses FastAPI",
        " project   alpha uses FASTAPI ",
    ])
    before = path.read_text(encoding="utf-8")

    report = apply_safe_cleanup(store, target="memory")
    out = handle_phi_memory_args(store, ["compress", "--target", "memory", "--apply-safe"])

    assert report["success"] is False
    assert "safe apply is disabled" in report["error"]
    assert "safe apply is disabled" in out
    assert path.read_text(encoding="utf-8") == before


def test_apply_safe_refuses_invalid_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    report = apply_safe_cleanup(store, target="banana")
    out = handle_phi_memory_args(store, ["compress", "--target", "banana", "--apply-safe"])

    assert report["success"] is False
    assert "Invalid --target" in report["error"]
    assert "Invalid --target" in out


def test_apply_safe_does_not_remove_unique_project_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "memory", [
        "Project alpha repo path /srv/alpha uses FastAPI",
        "Deploy alpha with queue_application_deployment force rebuild",
        "Runtime database name alpha.db",
    ])

    report = apply_safe_cleanup(store, target="memory")
    content = path.read_text(encoding="utf-8")

    assert report["success"] is True
    assert "Project alpha repo path /srv/alpha uses FastAPI" in content
    assert "queue_application_deployment" in content
    assert "alpha.db" in content


def test_apply_safe_keeps_protected_memory_types_unless_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store, path = _write_memory_file(tmp_path, "user", [
        "User prefers concise answers for debugging",
        "Correction: do not use browser keys in app runtime",
        "Decision: use Coolify for deployment",
        "Open loop: currently validate Betfair place prices",
        " user   prefers concise answers for debugging ",
    ])

    report = apply_safe_cleanup(store, target="user")
    content = path.read_text(encoding="utf-8")

    assert report["entries_removed"] == 1
    assert "User prefers concise answers for debugging" in content
    assert "Correction: do not use browser keys in app runtime" in content
    assert "Decision: use Coolify for deployment" in content
    assert "Open loop: currently validate Betfair place prices" in content


def test_auto_safe_cleanup_on_write_pressure_defaults_false(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cfg = phi_config()

    assert cfg["safe_apply_enabled"] is True
    assert cfg["auto_safe_cleanup_on_write_pressure"] is False


def test_auto_safe_cleanup_on_write_pressure_retries_once_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "memory:\n"
        "  phi:\n"
        "    auto_safe_cleanup_on_write_pressure: true\n"
        "    auto_safe_cleanup_threshold: 0.5\n",
        encoding="utf-8",
    )
    repeated = "Project alpha uses FastAPI and PostgreSQL"
    store, path = _write_memory_file(tmp_path, "memory", [repeated, repeated.upper()])
    store.memory_char_limit = len(path.read_text(encoding="utf-8")) + 5

    result = store.add("memory", "New durable project fact")
    content = path.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["phi"]["safe_cleanup_attempted"] is True
    assert "New durable project fact" in content
    assert content.count(repeated) == 1
