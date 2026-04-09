"""RED regression test for M9 — _session_id() must be defined.

The adversarial reviewer flagged that compress.py calls _session_id()
(with a leading underscore) while _session.py exports session_id
(no underscore). The current code aliases correctly:

    from token_sieve.cli._session import session_id as _session_id

but a refactor could break it. These tests pin down the contract so a
NameError never lurks behind broad except blocks.
"""
from __future__ import annotations

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    # We want the real _session_id path to be exercised, so leave the
    # bypass store alive but stub it to a fake that records calls.
    class FakeStore:
        def __init__(self) -> None:
            self.inline_sessions: list[str] = []
            self.passive_sessions: list[str] = []

        async def record_inline_bypass(self, cmd, session_id):
            self.inline_sessions.append(session_id)

        async def record_passive_reinforcement(self, cmd, session_id):
            self.passive_sessions.append(session_id)

        async def is_bypassed(self, cmd):
            return False

    fake = FakeStore()
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: fake)
    return fake


class TestSessionIdResolvable:
    def test_session_id_is_callable(self):
        assert callable(compress_mod._session_id)
        value = compress_mod._session_id()
        assert isinstance(value, str)
        assert len(value) >= 1

    def test_inline_bypass_path_calls_session_id_without_nameerror(
        self, monkeypatch, capsys, _no_bypass_store
    ):
        """TSIEV_INLINE_NO_COMPRESS=1 path invokes _session_id() (line ~288)."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo X'")
        monkeypatch.setenv("TSIEV_INLINE_NO_COMPRESS", "1")
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("CI_PIPELINE_ID", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-inline-m9")

        rc = run_compress([])

        assert rc == 0
        # _session_id should have been called and the session recorded.
        assert "sess-inline-m9" in _no_bypass_store.inline_sessions, (
            f"inline bypass path did not call _session_id(); "
            f"sessions={_no_bypass_store.inline_sessions!r}"
        )
