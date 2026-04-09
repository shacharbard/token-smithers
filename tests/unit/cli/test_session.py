"""RED tests for token_sieve.cli._session — M8 fallback collision.

Bug (M8): when CLAUDE_SESSION_ID is unset, session_id() returned the literal
'default', so every non-Claude invocation (cron jobs, scripts, manual CLI
runs) shared the same key, polluting ring-buffer counters, reinforcement
signals, and session aggregation. The fallback must be process-unique
(pid + start time) but stable across calls within the same process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap


class TestSessionIdM8Fallback:
    def test_env_var_takes_precedence(self, monkeypatch) -> None:
        """When CLAUDE_SESSION_ID is set, session_id returns it verbatim."""
        # Force a re-import so any module-level cache resets per-process.
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-abc123")

        # Bust any cached module state so the env var is observed.
        import importlib

        import token_sieve.cli._session as _session

        importlib.reload(_session)
        try:
            assert _session.session_id() == "claude-abc123"
        finally:
            importlib.reload(_session)  # reset for other tests

    def test_fallback_is_not_literal_default(self, monkeypatch) -> None:
        """Unset env var must NOT return the plain string 'default'."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

        import importlib

        import token_sieve.cli._session as _session

        importlib.reload(_session)
        try:
            sid = _session.session_id()
            assert sid != "default", (
                "Fallback must be process-unique, not the literal 'default' — "
                "M8 collision risk across non-Claude invocations"
            )
            # Must include the pid to be process-unique.
            assert str(os.getpid()) in sid, (
                f"Fallback should include pid={os.getpid()}, got {sid!r}"
            )
        finally:
            importlib.reload(_session)

    def test_fallback_is_stable_within_process(self, monkeypatch) -> None:
        """Multiple calls in the same process return the same fallback id."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

        import importlib

        import token_sieve.cli._session as _session

        importlib.reload(_session)
        try:
            first = _session.session_id()
            second = _session.session_id()
            assert first == second, (
                f"Fallback must be cached per-process, got {first!r} != {second!r}"
            )
        finally:
            importlib.reload(_session)

    def test_fallback_differs_across_processes(self) -> None:
        """Two subprocesses with no CLAUDE_SESSION_ID get different ids."""
        script = textwrap.dedent(
            """
            import os
            os.environ.pop("CLAUDE_SESSION_ID", None)
            from token_sieve.cli._session import session_id
            print(session_id())
            """
        )
        env = dict(os.environ)
        env.pop("CLAUDE_SESSION_ID", None)
        r1 = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        r2 = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        sid1 = r1.stdout.strip()
        sid2 = r2.stdout.strip()
        assert sid1 and sid2
        assert sid1 != sid2, (
            f"Two independent subprocesses must get different fallback ids, "
            f"got {sid1!r} == {sid2!r}"
        )
