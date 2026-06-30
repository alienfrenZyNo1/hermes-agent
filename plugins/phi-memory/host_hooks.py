#!/usr/bin/env python3
"""Install optional host-side hooks needed for Phi Memory write governance.

This is intentionally separate from normal plugin registration. A user plugin can
provide tools/commands, but automatic memory-write governance requires Hermes
core to expose and call a ``pre_memory_write`` hook.

The patcher is conservative:
- locates the active Hermes files by importing the installed ``hermes_cli`` and
  ``tools.memory_tool`` modules;
- creates timestamped backups before editing;
- uses exact/idempotent text patches for known Hermes layouts;
- refuses to patch if the expected anchors are not found.
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


HOOK_NAMES = ("pre_memory_write", "post_memory_write")


def _prepare_import_path() -> None:
    """Avoid plugin-local modules shadowing Hermes packages.

    When this file is executed as ``~/.hermes/plugins/phi-memory/host_hooks.py``,
    Python puts the plugin directory at ``sys.path[0]``. That directory also has
    ``tools.py``, which can shadow Hermes' top-level ``tools`` package while
    importing ``hermes_cli.plugins``. Remove the plugin directory from the import
    path; the real Hermes package remains discoverable through the installed
    ``hermes`` environment / current working directory.
    """
    plugin_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if str(Path(p or ".").resolve()) != plugin_dir]


class PatchError(RuntimeError):
    pass


def _module_file(module_name: str) -> Path:
    mod = importlib.import_module(module_name)
    path = getattr(mod, "__file__", None)
    if not path:
        raise PatchError(f"Could not locate module file for {module_name}")
    return Path(path).resolve()


def _backup(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.phi-memory-{ts}")
    shutil.copy2(path, backup)
    return backup


def _write_if_changed(path: Path, old: str, new: str, *, dry_run: bool) -> dict[str, Any]:
    if old == new:
        return {"path": str(path), "changed": False, "backup": None}
    if dry_run:
        return {"path": str(path), "changed": True, "backup": None, "dry_run": True}
    backup = _backup(path)
    path.write_text(new, encoding="utf-8")
    return {"path": str(path), "changed": True, "backup": str(backup)}


def patch_plugins_py(path: Path, *, dry_run: bool) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if all(name in text for name in HOOK_NAMES):
        return {"path": str(path), "changed": False, "already_supported": True}

    anchor = '    "post_tool_call",\n'
    insert = (
        '    "post_tool_call",\n'
        '    # Generic memory write governance hooks. Observers may reject/skip/transform\n'
        '    # a write before it is persisted, or request one deterministic retry on\n'
        '    # over-limit writes. Keep hook semantics generic; plugins decide policy.\n'
        '    "pre_memory_write",\n'
        '    "post_memory_write",\n'
    )
    if anchor not in text:
        raise PatchError(f"Could not find VALID_HOOKS insertion anchor in {path}")
    new = text.replace(anchor, insert, 1)
    return _write_if_changed(path, text, new, dry_run=dry_run)


_HELPER_INSERT_OLD = '''        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
'''

_HELPER_INSERT_NEW = '''        if scan_error:
            return {"success": False, "error": scan_error}

        def _invoke_memory_hooks(stage: str, **extra: Any) -> list:
            try:
                from hermes_cli.plugins import has_hook, invoke_hook
                if not has_hook("pre_memory_write"):
                    return []
                return invoke_hook(
                    "pre_memory_write",
                    action="add",
                    target=target,
                    content=content,
                    store=self,
                    stage=stage,
                    **extra,
                )
            except Exception:
                return []

        with self._file_lock(self._path_for(target)):
'''

_BEFORE_ADD_OLD = '''            # Reject exact duplicates
            if content in entries:
                return self._success_response(target, "Entry already exists (no duplicate added).")
'''

_BEFORE_ADD_NEW = '''            for hook_result in _invoke_memory_hooks(
                "before_add",
                entries=list(entries),
                limit=limit,
                already_locked=True,
            ):
                if not isinstance(hook_result, dict):
                    continue
                action = hook_result.get("action")
                if isinstance(hook_result.get("content"), str):
                    content = hook_result["content"].strip()
                    if not content:
                        return {"success": False, "error": "Content cannot be empty."}
                if action == "reject":
                    response = hook_result.get("response")
                    return response if isinstance(response, dict) else {"success": False, "error": hook_result.get("message", "Memory write rejected by plugin.")}
                if action == "skip":
                    return self._success_response(target, str(hook_result.get("message") or "Entry already exists (no duplicate added)."))

            # Core keeps backward-compatible exact duplicate behavior. Plugins
            # may add normalized/semantic duplicate policy via pre_memory_write.
            if content in entries:
                return self._success_response(target, "Entry already exists (no duplicate added).")
'''

_OVER_LIMIT_OLD = '''            if new_total > limit:
                current = self._char_count(target)
                return {
                    "success": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        f"Consolidate now: use 'replace' to merge overlapping entries into "
                        f"shorter ones or 'remove' stale or less important entries (see "
                        f"current_entries below), then retry this add — all in this turn."
                    ),
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }
'''

_OVER_LIMIT_NEW = '''            if new_total > limit:
                current = self._char_count(target)
                retry_metadata: Dict[str, Any] = {}
                for hook_result in _invoke_memory_hooks(
                    "over_limit",
                    entries=list(entries),
                    limit=limit,
                    current_chars=current,
                    new_total=new_total,
                    already_locked=True,
                ):
                    if isinstance(hook_result, dict):
                        metadata = hook_result.get("response_metadata")
                        if isinstance(metadata, dict):
                            retry_metadata.update(metadata)
                        if hook_result.get("action") == "retry":
                            entries = self._entries_for(target)
                            new_entries = entries + [content]
                            new_total = len(ENTRY_DELIMITER.join(new_entries))
                            if new_total <= limit:
                                entries.append(content)
                                self._set_entries(target, entries)
                                self.save_to_disk(target)
                                response = self._success_response(target, "Entry added after memory write hook retry.")
                                response.update(retry_metadata)
                                return response

                result = {
                    "success": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        f"Consolidate now: use 'replace' to merge overlapping entries into "
                        f"shorter ones or 'remove' stale or less important entries (see "
                        f"current_entries below), then retry this add — all in this turn."
                    ),
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }
                result.update(retry_metadata)
                return result
'''

_POST_ADD_OLD = '''            self.save_to_disk(target)

        return self._success_response(target, "Entry added.")
'''

_POST_ADD_NEW = '''            self.save_to_disk(target)

        try:
            from hermes_cli.plugins import has_hook, invoke_hook
            if has_hook("post_memory_write"):
                invoke_hook("post_memory_write", action="add", target=target, content=content, store=self)
        except Exception:
            pass

        return self._success_response(target, "Entry added.")
'''


def patch_memory_tool_py(path: Path, *, dry_run: bool) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "pre_memory_write" in text and "post_memory_write" in text:
        return {"path": str(path), "changed": False, "already_supported": True}

    new = text
    replacements = [
        (_HELPER_INSERT_OLD, _HELPER_INSERT_NEW, "helper insertion"),
        (_BEFORE_ADD_OLD, _BEFORE_ADD_NEW, "before_add hook insertion"),
        (_OVER_LIMIT_OLD, _OVER_LIMIT_NEW, "over_limit hook insertion"),
        (_POST_ADD_OLD, _POST_ADD_NEW, "post add hook insertion"),
    ]
    for old, replacement, label in replacements:
        if old not in new:
            raise PatchError(f"Could not find {label} anchor in {path}")
        new = new.replace(old, replacement, 1)

    return _write_if_changed(path, text, new, dry_run=dry_run)


def check_support() -> dict[str, Any]:
    result: dict[str, Any] = {"success": True}
    try:
        plugins_mod = importlib.import_module("hermes_cli.plugins")
        valid_hooks = getattr(plugins_mod, "VALID_HOOKS", set())
        result["pre_memory_write_supported"] = "pre_memory_write" in valid_hooks
        result["post_memory_write_supported"] = "post_memory_write" in valid_hooks
        result["plugins_py"] = str(_module_file("hermes_cli.plugins"))
    except Exception as exc:
        result["success"] = False
        result["plugins_error"] = f"{type(exc).__name__}: {exc}"
    try:
        memory_path = _module_file("tools.memory_tool")
        text = memory_path.read_text(encoding="utf-8")
        result["memory_tool_py"] = str(memory_path)
        result["memory_tool_invokes_pre_memory_write"] = "pre_memory_write" in text
    except Exception as exc:
        result["success"] = False
        result["memory_tool_error"] = f"{type(exc).__name__}: {exc}"
    return result


def install(*, dry_run: bool = False) -> dict[str, Any]:
    plugins_path = _module_file("hermes_cli.plugins")
    memory_path = _module_file("tools.memory_tool")
    patches = [
        patch_plugins_py(plugins_path, dry_run=dry_run),
        patch_memory_tool_py(memory_path, dry_run=dry_run),
    ]
    return {"success": True, "dry_run": dry_run, "patches": patches, "check_after_restart": check_support()}


def main(argv: list[str] | None = None) -> int:
    _prepare_import_path()
    parser = argparse.ArgumentParser(description="Install/check Phi Memory host hook support")
    parser.add_argument("--check", action="store_true", help="Check host hook support")
    parser.add_argument("--install", action="store_true", help="Patch active Hermes host files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args(argv)

    try:
        if args.install:
            result = install(dry_run=args.dry_run)
        else:
            result = check_support()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for key, value in result.items():
                print(f"{key}: {value}")
        return 0 if result.get("success") else 1
    except Exception as exc:
        result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(result["error"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
