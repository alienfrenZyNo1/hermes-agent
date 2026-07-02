"""Phi Memory v2 feature tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_cli.plugins import PluginManager, discover_plugins
from tools.memory_tool import MemoryStore


def _enable_phi_plugin(tmp_path: Path, extra_config: str = "") -> Path:
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - phi-memory\n"
        + extra_config,
        encoding="utf-8",
    )
    return home


def _write_memory(home: Path, target: str, entries: list[str]) -> Path:
    mem_dir = home / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    path = mem_dir / ("USER.md" if target == "user" else "MEMORY.md")
    path.write_text("\n§\n".join(entries), encoding="utf-8")
    return path


def _load_phi(tmp_path: Path, monkeypatch, entries: list[str] | None = None, extra_config: str = ""):
    home = _enable_phi_plugin(tmp_path, extra_config)
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_memory(home, "memory", entries or ["Project alpha uses FastAPI"])
    discover_plugins(force=True)
    return home, sys.modules["hermes_plugins.phi_memory"]


def test_metadata_sidecar_rebuild_validate_and_redacts_secrets(tmp_path, monkeypatch):
    home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["Project alpha uses FastAPI", "Project beta token=abcdefghijklmnop and path /home/lunafox/.secrets/key.json"],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    rebuilt = plugin.metadata.rebuild_sidecar(store, "memory")
    status = plugin.metadata.sidecar_status(store, "memory")
    validation = plugin.metadata.validate_sidecar(store, "memory")
    sidecar = Path(rebuilt["path"])
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    rendered = json.dumps(payload)

    assert rebuilt["success"] is True
    assert sidecar.name == "MEMORY.md.phi.json"
    assert status["status"] == "ok"
    assert validation["valid"] is True
    assert "abcdefghijklmnop" not in rendered
    assert ".secrets" not in rendered
    assert any(e["sensitive"] for e in payload["entries"].values())


def test_corrupt_sidecar_does_not_crash_and_reports_corrupt(tmp_path, monkeypatch):
    home, plugin = _load_phi(tmp_path, monkeypatch, ["Project alpha uses FastAPI"])
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    sidecar = home / "memories" / "MEMORY.md.phi.json"
    sidecar.write_text("{not json", encoding="utf-8")

    status = plugin.metadata.sidecar_status(store, "memory")
    validation = plugin.metadata.validate_sidecar(store, "memory")

    assert status["status"] == "corrupt"
    assert validation["valid"] is False


def test_recall_updates_metadata_access_count(tmp_path, monkeypatch):
    _home, plugin = _load_phi(tmp_path, monkeypatch, ["Coolify deployment uses force rebuild queue API"])
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    plugin.metadata.rebuild_sidecar(store, "memory")

    report = plugin.session_recall.recall_with_fallback(store, "coolify deployment", target="memory", active_only=True)
    sidecar = plugin.metadata.load_sidecar(store, "memory")
    counts = [entry["access_count"] for entry in sidecar["entries"].values()]

    assert report["hits"]
    assert report["hits"][0]["source"] == "active_memory"
    assert max(counts) == 1


def test_fibonacci_review_due_and_mark_reviewed_progresses_intervals(tmp_path, monkeypatch):
    _home, plugin = _load_phi(tmp_path, monkeypatch, ["Project alpha uses FastAPI"])
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    plugin.metadata.rebuild_sidecar(store, "memory")

    due = plugin.review.review_due(store, "memory", interactions=1)
    memory_id = due["due"][0]["memory_id"]
    first = plugin.review.mark_reviewed(store, "memory", memory_id, useful=True)
    second = plugin.review.mark_reviewed(store, "memory", memory_id, useful=True)

    assert due["due"][0]["suggested_action"] in {"keep", "promote", "compress", "archive", "convert_to_skill_candidate"}
    assert first["entry"]["review_interval_index"] == 1
    assert first["entry"]["next_review_after_interactions"] == 2
    assert second["entry"]["review_interval_index"] == 2
    assert second["entry"]["next_review_after_interactions"] == 3


def test_session_fallback_modes(monkeypatch, tmp_path):
    _home, plugin = _load_phi(tmp_path, monkeypatch, ["Unrelated project fact"])
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    def fake_search(query: str, limit: int = 3):
        return [{"source": "session_archive", "score": 0.77, "text": f"Archived hit for {query}", "session_id": "s1"}]

    active_only = plugin.session_recall.recall_with_fallback(store, "coolify deployment", target="memory", active_only=True, session_searcher=fake_search)
    fallback = plugin.session_recall.recall_with_fallback(store, "coolify deployment", target="memory", session_searcher=fake_search)
    forced = plugin.session_recall.recall_with_fallback(store, "coolify deployment", target="memory", include_session=True, session_searcher=fake_search)
    unavailable = plugin.session_recall.recall_with_fallback(
        store,
        "coolify deployment",
        target="memory",
        include_session=True,
        session_searcher=lambda _query, _limit: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    assert all(hit["source"] != "session_archive" for hit in active_only["hits"])
    assert any(hit["source"] == "session_archive" for hit in fallback["hits"])
    assert any(hit["source"] == "session_archive" for hit in forced["hits"])
    assert "session search unavailable" in unavailable["session_error"]


def test_skill_candidate_detection_and_draft_redacts(tmp_path, monkeypatch):
    _home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["When deploying Coolify, run force rebuild, then check logs, then restart exchange runner token=abcdefghijklmnop"],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    candidates = plugin.skills.find_skill_candidates(store, "memory")
    draft = plugin.skills.draft_skill(store, "memory", candidates["candidates"][0]["candidate_id"], write_file=True)

    assert candidates["candidates"]
    assert draft["success"] is True
    assert draft["path"].endswith(".md")
    assert "abcdefghijklmnop" not in draft["content"]
    assert "source_memory_ids" in draft["content"]


def test_semantic_compression_proposal_is_diff_only_and_preserves_exact_facts(tmp_path, monkeypatch):
    home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        [
            "RaceEdge production repo alienfrenZyNo1/raceedge deploys via Coolify app raceedge.",
            "RaceEdge production repo alienfrenZyNo1/raceedge deploys via Coolify app raceedge.",
            "Runtime DB is racing.db; research DB is racing-research.db.",
            "Debug note: tried random thing that was noisy and should be trimmed.",
        ],
    )
    store = MemoryStore(memory_char_limit=2200, user_char_limit=1000)
    store.load_from_disk()
    before = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    proposal = plugin.semantic.semantic_compression_proposal(store, "memory", budget=1400)
    after = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    assert proposal["success"] is True
    assert proposal["applied"] is False
    assert "alienfrenZyNo1/raceedge" in proposal["proposed_text"]
    assert "racing-research.db" in proposal["proposed_text"]
    assert "--- MEMORY.md before" in proposal["diff"]
    assert before == after


def test_semantic_compression_apply_requires_explicit_config(tmp_path, monkeypatch):
    home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        [
            "Project alpha repo /srv/alpha uses Postgres.",
            "Debug note: tried random thing that was noisy and should be trimmed.",
        ],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    before = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    report = plugin.semantic.apply_semantic_compression(store, "memory", budget=1000)
    after = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    assert report["success"] is False
    assert "semantic_compression_apply_enabled=false" in report["error"]
    assert before == after


def test_semantic_compression_apply_writes_backup_when_enabled(tmp_path, monkeypatch):
    home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        [
            "Project alpha repo /srv/alpha uses Postgres.",
            "Debug note: tried random thing that was noisy and should be trimmed.",
        ],
        extra_config="phi_memory:\n  semantic_compression_apply_enabled: true\n",
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    report = plugin.semantic.apply_semantic_compression(store, "memory", budget=1000)
    after = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    assert report["success"] is True
    assert report["applied"] is True
    assert Path(report["backup_path"]).exists()
    assert "Project alpha repo" in after
    assert "Debug note" not in after


def test_semantic_compression_apply_supports_user_profile(tmp_path, monkeypatch):
    home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["Project alpha uses FastAPI"],
        extra_config="phi_memory:\n  semantic_compression_apply_enabled: true\n",
    )
    _write_memory(
        home,
        "user",
        [
            "User prefers concise responses with exact verification.",
            "Debug note: tried random thing that was noisy and should be trimmed.",
        ],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    report = plugin.semantic.apply_semantic_compression(store, "user", budget=1000)
    after = (home / "memories" / "USER.md").read_text(encoding="utf-8")

    assert report["success"] is True
    assert report["applied"] is True
    assert Path(report["backup_path"]).exists()
    assert "User prefers concise responses" in after
    assert "Debug note" not in after


def test_auto_semantic_compression_on_write_pressure_is_opt_in(tmp_path, monkeypatch):
    home, _plugin = _load_phi(
        tmp_path,
        monkeypatch,
        [
            "Project alpha repo /srv/alpha uses Postgres and must keep exact path.",
            "Debug note: tried random thing that was noisy and should be trimmed during semantic compression.",
        ],
        extra_config=(
            "phi_memory:\n"
            "  semantic_compression_apply_enabled: true\n"
            "  auto_semantic_compression_on_write_pressure: true\n"
            "  auto_semantic_compression_threshold: 0.5\n"
            "  auto_semantic_compression_min_savings_chars: 1\n"
            "  auto_semantic_compression_targets:\n"
            "    - memory\n"
        ),
    )
    store = MemoryStore(memory_char_limit=145, user_char_limit=1000)
    store.load_from_disk()

    result = store.add("memory", "Remember this compact durable fact.")
    after = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["phi"]["semantic_compression_attempted"] is True
    assert result["phi"]["semantic_compression"]["applied"] is True
    assert Path(result["phi"]["semantic_compression"]["backup_path"]).exists()
    assert "Debug note" not in after
    assert "Remember this compact durable fact." in after


def test_auto_semantic_compression_on_write_pressure_supports_user_target(tmp_path, monkeypatch):
    home, _plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["Project alpha uses FastAPI"],
        extra_config=(
            "phi_memory:\n"
            "  semantic_compression_apply_enabled: true\n"
            "  auto_semantic_compression_on_write_pressure: true\n"
            "  auto_semantic_compression_threshold: 0.5\n"
            "  auto_semantic_compression_min_savings_chars: 1\n"
            "  auto_semantic_compression_targets:\n"
            "    - memory\n"
            "    - user\n"
        ),
    )
    _write_memory(
        home,
        "user",
        [
            "User prefers concise responses with exact verification.",
            "Debug note: tried random thing that was noisy and should be trimmed during semantic compression.",
        ],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=130)
    store.load_from_disk()

    result = store.add("user", "User values safe memory automation.")
    after = (home / "memories" / "USER.md").read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["phi"]["semantic_compression_attempted"] is True
    assert result["phi"]["semantic_compression"]["applied"] is True
    assert Path(result["phi"]["semantic_compression"]["backup_path"]).exists()
    assert "User prefers concise responses" in after
    assert "User values safe memory automation." in after
    assert "Debug note" not in after


def test_dashboard_text_and_json_include_health_fields(tmp_path, monkeypatch):
    _home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["Project alpha uses FastAPI", " project alpha uses FASTAPI ", "When deploying, run tests then build then deploy"],
    )
    store = MemoryStore(memory_char_limit=100, user_char_limit=1000)
    store.load_from_disk()
    plugin.metadata.rebuild_sidecar(store, "memory")

    data = plugin.dashboard.dashboard(store, target="memory")
    text = plugin.dashboard.format_dashboard(data)

    assert data["target"] == "memory"
    assert data["pressure"]["level"] in {"healthy", "review", "consolidate", "emergency"}
    assert data["sidecar"]["status"] == "ok"
    assert data["duplicates"]["normalized"] >= 1
    assert data["skill_candidates"] >= 1
    assert "Phi Memory Dashboard" in text


def test_cli_parser_accepts_v2_commands(tmp_path, monkeypatch, capsys):
    _home, _plugin = _load_phi(tmp_path, monkeypatch, ["Project alpha uses FastAPI"])
    mgr = PluginManager()
    mgr.discover_and_load(force=True)
    cmd = mgr._cli_commands["phi-memory"]
    parser = argparse.ArgumentParser()
    cmd["setup_fn"](parser)

    for argv in (["dashboard", "--json"], ["meta", "status", "--target", "memory"], ["review-due", "--target", "memory"], ["schedule", "--target", "memory"], ["skills", "candidates", "--target", "memory"], ["compress", "--target", "memory", "--semantic", "--budget", "1400"], ["compress", "--target", "memory", "--apply-semantic", "--budget", "1400"]):
        args = parser.parse_args(list(argv))
        cmd["handler_fn"](args)

    captured = capsys.readouterr().out
    assert "Phi Memory" in captured or "success" in captured


def test_semantic_proposal_and_recall_do_not_echo_raw_secrets(tmp_path, monkeypatch):
    _home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        [
            "Deploy repo alienfrenZyNo1/raceedge with token=abcdefghijklmnop and service key /home/lunafox/service-account-prod.json",
        ],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()

    proposal = plugin.semantic.semantic_compression_proposal(store, "memory", budget=1400)
    recall = plugin.session_recall.recall_with_fallback(store, "deploy repo", target="memory", active_only=True)
    rendered = json.dumps(proposal) + json.dumps(recall)

    assert "abcdefghijklmnop" not in rendered
    assert "service-account-prod.json" not in rendered
    assert "[REDACTED_SECRET" in rendered or "[REDACTED_SECRET_PATH]" in rendered


def test_skill_candidate_dismiss_and_draft_write_failure_degrades(tmp_path, monkeypatch):
    _home, plugin = _load_phi(
        tmp_path,
        monkeypatch,
        ["When deploying Coolify, run tests then build then deploy"],
    )
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    plugin.metadata.rebuild_sidecar(store, "memory")
    candidate = plugin.skills.find_skill_candidates(store, "memory")["candidates"][0]

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocked", encoding="utf-8")
    monkeypatch.setattr(plugin.skills, "get_hermes_home", lambda: blocked)
    draft = plugin.skills.draft_skill(store, "memory", candidate["candidate_id"], write_file=True)
    dismissed = plugin.skills.dismiss_candidate(store, "memory", candidate["candidate_id"])
    after = plugin.skills.find_skill_candidates(store, "memory")

    assert draft["success"] is True
    assert draft["path"] is None
    assert draft["write_error"]
    assert dismissed["dismissed"] is True
    assert after["count"] == 0
