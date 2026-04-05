"""Tests for hook installation in setup.py.

Tests install_hooks() function: creates entries in settings.json,
preserves existing hooks, idempotent, undo support, atomic writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


class TestInstallHooks:
    """Tests for install_hooks() function."""

    def test_install_hooks_creates_entries(self, tmp_path: Path) -> None:
        """install_hooks() adds PreToolUse entries to settings.json."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"

        result = install_hooks(settings_path)

        assert len(result) > 0
        data = json.loads(settings_path.read_text())
        assert "hooks" in data
        assert "PreToolUse" in data["hooks"]
        assert len(data["hooks"]["PreToolUse"]) > 0

    def test_install_hooks_preserves_existing(self, tmp_path: Path) -> None:
        """Existing hooks in settings.json are not clobbered."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "SomeOtherTool", "hooks": [{"type": "command", "command": "echo test"}]}
                ]
            },
            "other_setting": True,
        }
        settings_path.write_text(json.dumps(existing))

        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        # Original hook preserved
        matchers = [e["matcher"] for e in data["hooks"]["PreToolUse"]]
        assert "SomeOtherTool" in matchers
        # Token-sieve hooks added
        assert len(data["hooks"]["PreToolUse"]) > 1
        # Other settings preserved
        assert data["other_setting"] is True

    def test_install_hooks_idempotent(self, tmp_path: Path) -> None:
        """Running twice doesn't create duplicate entries."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"

        first = install_hooks(settings_path)
        second = install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        # Count token-sieve entries
        ts_entries = [
            e for e in data["hooks"]["PreToolUse"]
            if any("token-sieve" in str(h.get("command", "")) or "token_sieve" in str(h.get("command", ""))
                   for h in e.get("hooks", []))
        ]
        assert len(ts_entries) == len(first)

    def test_install_hooks_undo(self, tmp_path: Path) -> None:
        """install_hooks(undo=True) removes token-sieve hook entries."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"

        # Install first
        install_hooks(settings_path)
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["PreToolUse"]) > 0

        # Undo
        install_hooks(settings_path, undo=True)

        data = json.loads(settings_path.read_text())
        ts_entries = [
            e for e in data["hooks"].get("PreToolUse", [])
            if any("token-sieve" in str(h.get("command", "")) or "token_sieve" in str(h.get("command", ""))
                   for h in e.get("hooks", []))
        ]
        assert len(ts_entries) == 0

    def test_install_hooks_atomic_write(self, tmp_path: Path) -> None:
        """Uses tmp+rename pattern (no partial writes)."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        install_hooks(settings_path)

        # Verify file exists and is valid JSON (atomic write succeeded)
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data

        # No temp files left behind
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_install_hooks_handles_missing_file(self, tmp_path: Path) -> None:
        """Missing settings.json is created with empty base."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        assert not settings_path.exists()

        install_hooks(settings_path)

        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data


class TestSetupInstallHooksFlag:
    """Tests for --install-hooks CLI flag."""

    def test_setup_install_hooks_flag(self, tmp_path: Path, monkeypatch) -> None:
        """token-sieve setup --install-hooks triggers hook installation."""
        from token_sieve.cli.main import main

        # Mock settings path to avoid touching real settings
        settings_path = tmp_path / "settings.json"
        monkeypatch.setenv("TOKEN_SIEVE_SETTINGS_PATH", str(settings_path))

        # Mock discover_mcp_configs to avoid real filesystem scan
        monkeypatch.setattr(
            "token_sieve.cli.setup.discover_mcp_configs",
            lambda *a, **kw: [],
        )

        result = main(["setup", "--install-hooks"])
        assert result == 0

        # Verify hooks were installed
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data


class TestSettingsJsonSafety:
    """H4+H5+M7: Settings.json safety fixes."""

    def test_malformed_json_raises_error(self, tmp_path: Path) -> None:
        """H4: Malformed settings.json must raise an error, not silently replace."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"hooks": {}, "important": true,}')  # trailing comma

        with pytest.raises((json.JSONDecodeError, ValueError)):
            install_hooks(settings_path)

        # Original file should be untouched
        assert settings_path.read_text() == '{"hooks": {}, "important": true,}'

    def test_backup_created_before_modification(self, tmp_path: Path) -> None:
        """H5: backup_config() must be called before modifying settings.json."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        original_data = {"existing_setting": True, "hooks": {}}
        settings_path.write_text(json.dumps(original_data))

        install_hooks(settings_path)

        backup_path = settings_path.with_suffix(".json.backup")
        assert backup_path.exists(), "No backup created before modification"
        backup_data = json.loads(backup_path.read_text())
        assert backup_data["existing_setting"] is True

    def test_undo_flag_passed_through_run_setup(self, tmp_path: Path, monkeypatch) -> None:
        """M7: --undo --install-hooks must remove hooks, not install them."""
        from token_sieve.cli.setup import install_hooks, run_setup

        settings_path = tmp_path / "settings.json"
        monkeypatch.setenv("TOKEN_SIEVE_SETTINGS_PATH", str(settings_path))

        # Install hooks first
        install_hooks(settings_path)
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["PreToolUse"]) > 0

        # Now run_setup with undo=True and install_hooks_flag=True
        run_setup(undo=True, install_hooks_flag=True)

        data = json.loads(settings_path.read_text())
        ts_entries = [
            e for e in data["hooks"].get("PreToolUse", [])
            if any(
                "token-sieve" in str(h.get("command", ""))
                or "token_sieve" in str(h.get("command", ""))
                for h in e.get("hooks", [])
            )
        ]
        assert len(ts_entries) == 0, "Undo did not remove hooks"
