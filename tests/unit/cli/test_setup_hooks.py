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


class TestNewHookWiring:
    """Tests for bash-compress-rewrite + webfetch-redirect wiring (09-02)."""

    def test_install_hooks_adds_bash_compress_rewrite(self, tmp_path: Path) -> None:
        """install_hooks() adds a Bash entry whose command references bash-compress-rewrite.sh."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        bash_entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Bash"
        ]
        compress_entries = [
            e for e in bash_entries
            if any("bash-compress-rewrite.sh" in str(h.get("command", ""))
                   for h in e.get("hooks", []))
        ]
        assert len(compress_entries) >= 1, (
            "No Bash entry referencing bash-compress-rewrite.sh found. "
            f"Bash entries: {bash_entries}"
        )

    def test_install_hooks_adds_webfetch_redirect(self, tmp_path: Path) -> None:
        """install_hooks() adds a WebFetch entry whose command references webfetch-redirect.sh."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        wf_entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "WebFetch"
            and any("webfetch-redirect.sh" in str(h.get("command", ""))
                    for h in e.get("hooks", []))
        ]
        assert len(wf_entries) >= 1, (
            "No WebFetch entry referencing webfetch-redirect.sh found. "
            f"All entries: {data['hooks']['PreToolUse']}"
        )

    def test_compress_rewrite_after_edge_redirect(self, tmp_path: Path) -> None:
        """bash-compress-rewrite entry appears AFTER bash-edge-redirect in PreToolUse list (D11)."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        # Pre-populate with an edge-redirect entry (simulating earlier install)
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash-edge-redirect.sh token-sieve",
                            }
                        ],
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(existing))

        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        entries = data["hooks"]["PreToolUse"]
        edge_idx = next(
            (i for i, e in enumerate(entries)
             if any("bash-edge-redirect.sh" in str(h.get("command", ""))
                    for h in e.get("hooks", []))),
            None,
        )
        compress_idx = next(
            (i for i, e in enumerate(entries)
             if any("bash-compress-rewrite.sh" in str(h.get("command", ""))
                    for h in e.get("hooks", []))),
            None,
        )
        assert edge_idx is not None, "bash-edge-redirect.sh entry not found"
        assert compress_idx is not None, "bash-compress-rewrite.sh entry not found"
        assert edge_idx < compress_idx, (
            f"D11 violated: bash-edge-redirect (idx {edge_idx}) must precede "
            f"bash-compress-rewrite (idx {compress_idx})"
        )

    def test_no_duplicate_install(self, tmp_path: Path) -> None:
        """Calling install_hooks() twice produces exactly one bash-compress-rewrite entry."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        install_hooks(settings_path)
        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        compress_entries = [
            e for e in data["hooks"]["PreToolUse"]
            if any("bash-compress-rewrite.sh" in str(h.get("command", ""))
                   for h in e.get("hooks", []))
        ]
        assert len(compress_entries) == 1, (
            f"Expected exactly 1 bash-compress-rewrite entry, got {len(compress_entries)}"
        )

    def test_undo_removes_both_new_hooks(self, tmp_path: Path) -> None:
        """install_hooks(undo=True) removes bash-compress-rewrite and webfetch-redirect entries."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        install_hooks(settings_path)

        # Verify both entries exist
        data = json.loads(settings_path.read_text())
        assert any(
            "bash-compress-rewrite.sh" in str(h.get("command", ""))
            for e in data["hooks"]["PreToolUse"]
            for h in e.get("hooks", [])
        ), "bash-compress-rewrite.sh not installed"
        assert any(
            "webfetch-redirect.sh" in str(h.get("command", ""))
            for e in data["hooks"]["PreToolUse"]
            for h in e.get("hooks", [])
        ), "webfetch-redirect.sh not installed"

        # Undo
        install_hooks(settings_path, undo=True)

        data = json.loads(settings_path.read_text())
        remaining = data["hooks"].get("PreToolUse", [])
        compress_remains = any(
            "bash-compress-rewrite.sh" in str(h.get("command", ""))
            for e in remaining
            for h in e.get("hooks", [])
        )
        webfetch_remains = any(
            "webfetch-redirect.sh" in str(h.get("command", ""))
            for e in remaining
            for h in e.get("hooks", [])
        )
        assert not compress_remains, "bash-compress-rewrite.sh not removed by undo"
        assert not webfetch_remains, "webfetch-redirect.sh not removed by undo"


class TestInstallHooksH6Concurrency:
    """H6: install_hooks must hold an exclusive flock and fsync writes."""

    def test_concurrent_installs_do_not_corrupt_json(
        self, tmp_path: Path
    ) -> None:
        """Two threads installing at once produce valid JSON with no data loss."""
        import threading

        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        # Seed with a benign pre-existing unrelated setting
        settings_path.write_text(json.dumps({"seeded": True, "hooks": {"PreToolUse": []}}))

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                install_hooks(settings_path)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent install raised: {errors}"

        # File must still be valid JSON after concurrent writes.
        data = json.loads(settings_path.read_text())
        # The pre-existing seeded key must survive all races.
        assert data.get("seeded") is True, (
            "Concurrent install clobbered unrelated settings key — last-writer-wins corruption"
        )
        # Hooks must be installed exactly once (dedup must hold across races).
        pre_tool_use = data.get("hooks", {}).get("PreToolUse", [])
        bash_compress_count = sum(
            1
            for e in pre_tool_use
            for h in e.get("hooks", [])
            if "bash-compress-rewrite.sh" in str(h.get("command", ""))
        )
        assert bash_compress_count == 1, (
            f"Expected exactly 1 bash-compress-rewrite hook entry, got {bash_compress_count}"
        )

    def test_atomic_write_fsyncs_tmp_and_parent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_atomic_write must fsync the tmp file fd before rename and the parent dir after."""
        import os as os_mod

        if os_mod.name != "posix":
            pytest.skip("POSIX-only: fsync of parent dir is not meaningful on Windows")

        from token_sieve.cli import setup as setup_mod

        fsync_calls: list[int] = []
        original_fsync = os_mod.fsync

        def tracking_fsync(fd: int) -> None:
            fsync_calls.append(fd)
            original_fsync(fd)

        monkeypatch.setattr(setup_mod.os, "fsync", tracking_fsync, raising=False)
        # Also cover top-level os module lookups
        monkeypatch.setattr("os.fsync", tracking_fsync)

        settings_path = tmp_path / "settings.json"
        setup_mod._atomic_write(settings_path, {"ok": True})

        assert len(fsync_calls) >= 2, (
            f"Expected fsync on tmp fd AND parent dir fd, got {len(fsync_calls)} call(s)"
        )
        # And the file landed
        assert json.loads(settings_path.read_text()) == {"ok": True}


class TestInstallHooksH6DedupPrecision:
    """H6: dedup must not collapse hooks whose command contains a superstring of ours."""

    def test_dedup_does_not_collide_with_superstring_scripts(
        self, tmp_path: Path
    ) -> None:
        """A pre-existing hook whose command contains 'pre-bash-compress-rewrite.sh'
        must not prevent installation of our 'bash-compress-rewrite.sh' hook."""
        from token_sieve.cli.setup import install_hooks

        settings_path = tmp_path / "settings.json"
        # Seed with a foreign hook whose script name is a SUPERSTRING of ours.
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        # Contains 'bash-compress-rewrite.sh' as a substring
                                        # — substring `in` check would falsely match.
                                        "command": "bash /some/path/pre-bash-compress-rewrite.sh",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )

        install_hooks(settings_path)

        data = json.loads(settings_path.read_text())
        pre_tool_use = data["hooks"]["PreToolUse"]

        # Collect commands that end in the EXACT script name we care about.
        def is_ours(h_cmd: str) -> bool:
            # An "ours" hook ends with `bash-compress-rewrite.sh  # token-sieve`
            return "# token-sieve" in h_cmd and "bash-compress-rewrite.sh" in h_cmd

        ours_count = sum(
            1
            for e in pre_tool_use
            for h in e.get("hooks", [])
            if is_ours(str(h.get("command", "")))
        )
        assert ours_count == 1, (
            f"Expected our bash-compress-rewrite.sh hook to be installed "
            f"despite superstring collision, got {ours_count}"
        )

        # Original foreign hook must also still be present.
        foreign_remains = any(
            "pre-bash-compress-rewrite.sh" in str(h.get("command", ""))
            for e in pre_tool_use
            for h in e.get("hooks", [])
        )
        assert foreign_remains, "Foreign pre-existing hook was removed"
