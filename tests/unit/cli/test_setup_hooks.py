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
