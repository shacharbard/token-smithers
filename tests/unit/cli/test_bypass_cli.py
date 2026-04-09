"""RED tests for bypass CLI subcommand + stats surfacing.

Task 5 of 09-04: verify token-sieve bypass add/remove/list CLI commands
work correctly, and that token-sieve stats surfaces bypass auto-learn count
and compression error telemetry.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore


@pytest.fixture()
async def temp_db():
    """Create a temp file-backed SQLite store for bypass CLI tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = await SQLiteLearningStore.connect(db_path)
    try:
        yield db_path, store
    finally:
        await store.close()
        for ext in ["", "-wal", "-shm"]:
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


class TestBypassCLI:
    """Tests for the bypass add/remove/list subcommand."""

    async def test_bypass_add_persists(self, temp_db) -> None:
        """bypass add <pattern> → row in bypass_rules with source='manual'."""
        db_path, store = temp_db

        from token_sieve.cli.bypass import run_bypass

        with patch.dict("os.environ", {"TOKEN_SIEVE_LEARNING_DB": db_path}):
            rc = run_bypass(["add", "kubectl get secret"])

        assert rc == 0

        async with store._db.execute(
            "SELECT pattern, source FROM bypass_rules WHERE pattern=?",
            ("kubectl get secret",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "bypass_rules row should be created"
        assert row[1] == "manual"

    async def test_bypass_remove_deletes(self, temp_db) -> None:
        """bypass remove <pattern> → row removed from bypass_rules."""
        db_path, store = temp_db
        now = datetime.now(timezone.utc).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'manual', ?, ?, 0, 1)
            """,
            ("kubectl get secret", now, now),
        )
        await store._db.commit()

        from token_sieve.cli.bypass import run_bypass

        with patch.dict("os.environ", {"TOKEN_SIEVE_LEARNING_DB": db_path}):
            rc = run_bypass(["remove", "kubectl get secret"])

        assert rc == 0

        async with store._db.execute(
            "SELECT pattern FROM bypass_rules WHERE pattern=?",
            ("kubectl get secret",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is None, "Row should be removed from bypass_rules"

    async def test_bypass_list_includes_source(self, temp_db, capsys) -> None:
        """bypass list → stdout shows pattern + source + last_reinforced."""
        db_path, store = temp_db
        now = datetime.now(timezone.utc).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'manual', ?, ?, 0, 1)
            """,
            ("pytest tests/auth", now, now),
        )
        await store._db.commit()

        from token_sieve.cli.bypass import run_bypass

        with patch.dict("os.environ", {"TOKEN_SIEVE_LEARNING_DB": db_path}):
            rc = run_bypass(["list"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "pytest tests/auth" in captured.out
        assert "manual" in captured.out

    def test_main_dispatches_bypass(self, monkeypatch) -> None:
        """token_sieve.cli.main.main(['bypass', 'add', 'x']) → routes to bypass.run_bypass."""
        from token_sieve.cli.main import main

        dispatched = []

        with patch("token_sieve.cli.bypass.run_bypass") as mock_bypass:
            mock_bypass.side_effect = lambda argv: dispatched.append(argv) or 0
            rc = main(["bypass", "add", "x"])

        assert rc == 0
        assert dispatched == [["add", "x"]]


class TestStatsWithBypass:
    """Tests for stats surfacing of bypass + error telemetry."""

    async def test_stats_includes_BYPASS_AUTO_LEARNED_count(
        self, temp_db, capsys
    ) -> None:
        """Pre-populate bypass_events with auto_learned rows → stats shows count."""
        db_path, store = temp_db

        now = datetime.now(timezone.utc).isoformat()
        # Insert 3 auto_learned events
        for i in range(3):
            await store._db.execute(
                """
                INSERT INTO bypass_events (pattern, occurred_at, kind, session_id, ci_detected)
                VALUES (?, ?, 'auto_learned', ?, 0)
                """,
                (f"pattern_{i}", now, f"s{i}"),
            )
        await store._db.commit()

        with patch.dict(
            "os.environ",
            {
                "TOKEN_SIEVE_LEARNING_DB": db_path,
                "TOKEN_SIEVE_METRICS_PATH": "/nonexistent/metrics.json",
            },
        ):
            from token_sieve.cli.main import _run_stats
            # Call full stats (full=True) which pulls from learning DB
            with patch("pathlib.Path.exists", return_value=False):
                # Stats without metrics file will show error, but we test the learning DB stats path
                pass
            # Use a valid but minimal metrics file
            import json
            import tempfile

            metrics_data = {
                "session_summary": {
                    "total_savings_ratio": 0.3,
                    "total_original_tokens": 1000,
                    "total_compressed_tokens": 700,
                    "event_count": 10,
                },
                "strategy_breakdown": {},
            }
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(metrics_data, f)
                metrics_path = f.name

        try:
            with patch.dict(
                "os.environ",
                {
                    "TOKEN_SIEVE_LEARNING_DB": db_path,
                    "TOKEN_SIEVE_METRICS_PATH": metrics_path,
                },
            ):
                from token_sieve.cli.main import _run_stats

                rc = _run_stats(full=True)

            captured = capsys.readouterr()
            assert rc == 0
            # Should mention bypass auto-learned count in full report
            # "Bypass auto-learned" is new text we'll add — check for the specific phrase
            assert "bypass auto-learned" in captured.out.lower(), (
                f"Expected 'Bypass auto-learned' in stats output, got: {captured.out[:500]}"
            )
        finally:
            os.unlink(metrics_path)

    async def test_stats_includes_compression_errors_section(
        self, temp_db, capsys
    ) -> None:
        """Pre-populate compression_errors → stats shows error telemetry."""
        db_path, store = temp_db

        # Create compression_errors table and insert 3 rows
        await store._db.execute(
            """
            CREATE TABLE IF NOT EXISTS compression_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                adapter_name TEXT NOT NULL,
                exc_type TEXT NOT NULL,
                pattern_hash TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                session_id TEXT NOT NULL
            )
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            await store._db.execute(
                """
                INSERT INTO compression_errors (adapter_name, exc_type, pattern_hash, occurred_at, session_id)
                VALUES ('compress_cli', 'RuntimeError', ?, ?, ?)
                """,
                (f"hash{i}", now, f"s{i}"),
            )
        await store._db.commit()

        import json
        import tempfile

        metrics_data = {
            "session_summary": {
                "total_savings_ratio": 0.2,
                "total_original_tokens": 500,
                "total_compressed_tokens": 400,
                "event_count": 5,
            },
            "strategy_breakdown": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(metrics_data, f)
            metrics_path = f.name

        try:
            with patch.dict(
                "os.environ",
                {
                    "TOKEN_SIEVE_LEARNING_DB": db_path,
                    "TOKEN_SIEVE_METRICS_PATH": metrics_path,
                },
            ):
                from token_sieve.cli.main import _run_stats

                rc = _run_stats(full=True)

            captured = capsys.readouterr()
            assert rc == 0
            # Should mention compression errors with the new specific phrase we'll add
            assert "compression errors" in captured.out.lower(), (
                f"Expected 'Compression errors' in stats output, got: {captured.out[:500]}"
            )
        finally:
            os.unlink(metrics_path)


class TestBypassCLIAuditLogM10:
    """M10: bypass add/remove must append a JSONL audit record.

    Any local shell user with write access to the learning DB can currently
    poison bypass rules silently — there is no trail of who did what, when,
    or via which source. The CLI must append a line to an audit log so
    operators can detect tampering.
    """

    async def test_bypass_add_appends_audit_line(
        self, temp_db, tmp_path, monkeypatch
    ) -> None:
        db_path, _store = temp_db
        audit_path = tmp_path / "bypass-audit.log"

        from token_sieve.cli.bypass import run_bypass

        monkeypatch.setenv("TOKEN_SIEVE_LEARNING_DB", db_path)
        monkeypatch.setenv("TOKEN_SIEVE_BYPASS_AUDIT_LOG", str(audit_path))

        rc = run_bypass(["add", "kubectl get secret"])
        assert rc == 0

        assert audit_path.exists(), "Audit log file must be created on bypass add"
        lines = audit_path.read_text().splitlines()
        assert len(lines) == 1, f"Expected exactly 1 audit line, got {len(lines)}"

        entry = json.loads(lines[0])
        assert entry["action"] == "add"
        assert entry["pattern"] == "kubectl get secret"
        assert entry["source"] == "manual"
        assert "timestamp" in entry and entry["timestamp"]
        assert "user" in entry and entry["user"], "Audit entry must include user"

    async def test_bypass_remove_appends_audit_line(
        self, temp_db, tmp_path, monkeypatch
    ) -> None:
        db_path, _store = temp_db
        audit_path = tmp_path / "bypass-audit.log"

        from token_sieve.cli.bypass import run_bypass

        monkeypatch.setenv("TOKEN_SIEVE_LEARNING_DB", db_path)
        monkeypatch.setenv("TOKEN_SIEVE_BYPASS_AUDIT_LOG", str(audit_path))

        # Seed a rule first (this also writes an audit line)
        assert run_bypass(["add", "vault read secret/x"]) == 0
        # Then remove
        rc = run_bypass(["remove", "vault read secret/x"])
        assert rc == 0

        lines = audit_path.read_text().splitlines()
        assert len(lines) == 2, (
            f"Expected 2 audit lines (add + remove), got {len(lines)}"
        )

        remove_entry = json.loads(lines[1])
        assert remove_entry["action"] == "remove"
        assert remove_entry["pattern"] == "vault read secret/x"
        assert "timestamp" in remove_entry

    async def test_bypass_add_succeeds_even_if_audit_write_fails(
        self, temp_db, tmp_path, monkeypatch, capsys
    ) -> None:
        """Audit log is best-effort — a failed audit write must not break the CLI."""
        db_path, _store = temp_db
        # Point audit log at an unwritable path (directory that doesn't exist
        # and can't be created because its parent is a regular file)
        bad_parent = tmp_path / "not_a_dir"
        bad_parent.write_text("blocker")
        bad_audit = bad_parent / "nested" / "bypass-audit.log"

        from token_sieve.cli.bypass import run_bypass

        monkeypatch.setenv("TOKEN_SIEVE_LEARNING_DB", db_path)
        monkeypatch.setenv("TOKEN_SIEVE_BYPASS_AUDIT_LOG", str(bad_audit))

        rc = run_bypass(["add", "aws sts get-caller-identity"])
        assert rc == 0, "bypass add must succeed even when audit write fails"
