"""Tests for InMemorySessionRepo and SessionContext.

TDD RED phase: these tests define the session contract before implementation.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from token_sieve.domain.ports import SessionRepository


class TestSessionContext:
    """SessionContext entity tracks per-session state."""

    def test_session_context_creation(self):
        from token_sieve.domain.session import SessionContext

        ctx = SessionContext(session_id="s1")
        assert ctx.session_id == "s1"
        assert ctx.seen_hashes == set()
        assert ctx.result_count == 0
        assert isinstance(ctx.created_at, datetime)

    def test_session_context_tracks_seen_hashes(self):
        from token_sieve.domain.session import SessionContext

        ctx = SessionContext(session_id="s1")
        ctx.seen_hashes.add("hash1")
        ctx.seen_hashes.add("hash2")

        assert "hash1" in ctx.seen_hashes
        assert "hash2" in ctx.seen_hashes
        assert len(ctx.seen_hashes) == 2

    def test_session_context_add_result_hash(self):
        from token_sieve.domain.session import SessionContext

        ctx = SessionContext(session_id="s1")
        ctx.add_result_hash("abc123")
        ctx.add_result_hash("def456")

        assert "abc123" in ctx.seen_hashes
        assert ctx.result_count == 2

    def test_session_context_add_result_hash_dedup(self):
        """Adding same hash twice only increments result_count once."""
        from token_sieve.domain.session import SessionContext

        ctx = SessionContext(session_id="s1")
        ctx.add_result_hash("abc123")
        ctx.add_result_hash("abc123")

        assert len(ctx.seen_hashes) == 1
        assert ctx.result_count == 1

    def test_session_context_is_mutable(self):
        from token_sieve.domain.session import SessionContext

        ctx = SessionContext(session_id="s1")
        ctx.result_count = 5
        assert ctx.result_count == 5


class TestInMemorySessionRepo:
    """InMemorySessionRepo stores sessions in a plain dict."""

    def test_get_nonexistent_returns_none(self):
        from token_sieve.domain.session import InMemorySessionRepo

        repo = InMemorySessionRepo()
        assert repo.get("nonexistent") is None

    def test_save_and_get_roundtrip(self):
        from token_sieve.domain.session import InMemorySessionRepo, SessionContext

        repo = InMemorySessionRepo()
        ctx = SessionContext(session_id="s1")
        ctx.add_result_hash("hash1")

        repo.save(ctx)
        retrieved = repo.get("s1")

        assert retrieved is not None
        assert retrieved.session_id == "s1"
        assert "hash1" in retrieved.seen_hashes

    def test_save_overwrites_existing(self):
        from token_sieve.domain.session import InMemorySessionRepo, SessionContext

        repo = InMemorySessionRepo()
        ctx1 = SessionContext(session_id="s1")
        ctx1.add_result_hash("hash1")
        repo.save(ctx1)

        ctx2 = SessionContext(session_id="s1")
        ctx2.add_result_hash("hash2")
        repo.save(ctx2)

        retrieved = repo.get("s1")
        assert retrieved is not None
        assert "hash2" in retrieved.seen_hashes
        assert "hash1" not in retrieved.seen_hashes

    def test_satisfies_session_repository_protocol(self):
        from token_sieve.domain.session import InMemorySessionRepo

        repo = InMemorySessionRepo()
        # Structural subtyping check: has get() and save() with right signatures
        assert hasattr(repo, "get")
        assert hasattr(repo, "save")
        # Verify callable
        assert callable(repo.get)
        assert callable(repo.save)

    # --- Finding 6: bounded growth ---

    def test_evicts_oldest_session_at_cap(self):
        from token_sieve.domain.session import (
            DEFAULT_MAX_SESSIONS,
            InMemorySessionRepo,
            SessionContext,
        )

        repo = InMemorySessionRepo(max_sessions=3)
        for i in range(5):
            repo.save(SessionContext(session_id=f"s{i}"))

        # s0 and s1 evicted (oldest by created_at)
        assert repo.get("s0") is None
        assert repo.get("s1") is None
        assert repo.get("s2") is not None
        assert repo.get("s3") is not None
        assert repo.get("s4") is not None

    def test_default_max_sessions_is_100(self):
        from token_sieve.domain.session import DEFAULT_MAX_SESSIONS

        assert DEFAULT_MAX_SESSIONS == 100
