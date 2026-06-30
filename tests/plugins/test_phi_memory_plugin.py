"""Integration tests for bundled phi-memory plugin surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_cli import plugins as plugins_mod
from hermes_cli.plugins import PluginManager
from tools.memory_tool import MemoryStore
from tools.registry import registry


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


def test_phi_memory_plugin_discovers_tool_slash_cli_and_optional_hook(tmp_path, monkeypatch):
    home = _enable_phi_plugin(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    mgr = PluginManager()
    mgr.discover_and_load()

    loaded = mgr._plugins["phi-memory"]
    assert loaded.enabled is True
    assert "phi_memory" in loaded.tools_registered
    if "pre_memory_write" in plugins_mod.VALID_HOOKS:
        assert "pre_memory_write" in loaded.hooks_registered
    else:
        assert "pre_memory_write" not in loaded.hooks_registered
    assert "phi-memory" in mgr._plugin_commands
    assert "phi-memory" in mgr._cli_commands


def test_phi_memory_plugin_skips_memory_hook_on_older_hosts(tmp_path, monkeypatch, caplog):
    home = _enable_phi_plugin(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(
        plugins_mod,
        "VALID_HOOKS",
        set(plugins_mod.VALID_HOOKS) - {"pre_memory_write"},
    )

    mgr = PluginManager()
    mgr.discover_and_load()

    loaded = mgr._plugins["phi-memory"]
    assert loaded.enabled is True
    assert "phi_memory" in loaded.tools_registered
    assert "pre_memory_write" not in loaded.hooks_registered
    assert "registered unknown hook 'pre_memory_write'" not in caplog.text


def test_phi_memory_plugin_disabled_does_not_govern_memory_writes(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    mgr = PluginManager()
    mgr.discover_and_load()
    store = MemoryStore(memory_char_limit=1000, user_char_limit=1000)
    store.load_from_disk()
    first = store.add("memory", "Project alpha uses FastAPI")
    second = store.add("memory", " project   alpha uses FASTAPI ")

    assert "phi-memory" not in mgr._plugins or not mgr._plugins["phi-memory"].enabled
    assert first["success"] is True
    assert second["success"] is True
    assert len(store._entries_for("memory")) == 2


def test_phi_memory_tool_actions_and_safe_apply(tmp_path, monkeypatch):
    home = _enable_phi_plugin(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    path = _write_memory(home, "memory", [
        "Project alpha uses FastAPI",
        " project   alpha uses FASTAPI ",
    ])
    PluginManager().discover_and_load()

    dry = json.loads(registry.dispatch("phi_memory", {"action": "compress", "target": "memory"}))
    assert dry["success"] is True
    assert dry["dry_run"] is True
    assert path.read_text(encoding="utf-8").count("FASTAPI") == 1

    applied = json.loads(registry.dispatch("phi_memory", {"action": "compress", "target": "memory", "apply_safe": True}))
    assert applied["success"] is True
    assert applied["applied"] is True
    assert applied["entries_removed"] == 1
    assert applied["backup_path"]
    assert list((home / "memories").glob("MEMORY.md.bak.*"))


def test_phi_memory_slash_command_parsing(tmp_path, monkeypatch):
    home = _enable_phi_plugin(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_memory(home, "memory", ["Project alpha uses FastAPI"])
    mgr = PluginManager()
    mgr.discover_and_load()

    out = mgr._plugin_commands["phi-memory"]["handler"]("status --target memory")

    assert "Phi Memory memory" in out
    assert "Dry run: True" in out


def test_phi_memory_cli_command_parsing(tmp_path, monkeypatch, capsys):
    home = _enable_phi_plugin(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_memory(home, "memory", ["Project alpha uses FastAPI"])
    mgr = PluginManager()
    mgr.discover_and_load()
    cmd = mgr._cli_commands["phi-memory"]
    parser = argparse.ArgumentParser()
    cmd["setup_fn"](parser)
    args = parser.parse_args(["status", "--target", "memory"])

    cmd["handler_fn"](args)
    captured = capsys.readouterr().out

    assert "Phi Memory memory" in captured


def test_memory_phi_legacy_config_is_respected(tmp_path, monkeypatch):
    home = _enable_phi_plugin(
        tmp_path,
        "memory:\n"
        "  phi:\n"
        "    safe_apply_enabled: false\n",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_memory(home, "memory", ["Project alpha uses FastAPI", " project alpha uses FASTAPI "])
    mgr = PluginManager()
    mgr.discover_and_load()

    out = mgr._plugin_commands["phi-memory"]["handler"]("compress --target memory --apply-safe")

    assert "safe apply is disabled" in out


def test_phi_memory_new_plugin_config_preferred_when_both_exist(tmp_path, monkeypatch):
    home = _enable_phi_plugin(
        tmp_path,
        "memory:\n"
        "  phi:\n"
        "    safe_apply_enabled: false\n"
        "phi_memory:\n"
        "  safe_apply_enabled: true\n",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    _write_memory(home, "memory", ["Project alpha uses FastAPI", " project alpha uses FASTAPI "])
    mgr = PluginManager()
    mgr.discover_and_load()

    out = mgr._plugin_commands["phi-memory"]["handler"]("compress --target memory --apply-safe")

    assert "safe apply is disabled" not in out
    assert "applied=True" in out
