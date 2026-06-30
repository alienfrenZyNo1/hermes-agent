"""Tests for Phi Memory governance."""

import json

import pytest

from tools.memory_tool import MemoryStore, memory_tool
from tools.phi_memory import (
    PHI,
    PHI_HARD_WARNING,
    PHI_MAJOR,
    PHI_MINOR,
    explain_text,
    handle_phi_memory_args,
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
