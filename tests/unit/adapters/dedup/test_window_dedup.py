"""Tests for WindowDeduplicationStrategy adapter.

Inherits DeduplicationStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import DeduplicationStrategyContract
from token_sieve.adapters.dedup.window_dedup import WindowDeduplicationStrategy
from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.session import SessionContext


@pytest.fixture()
def dedup_strategy():
    """Provide WindowDeduplicationStrategy for contract tests."""
    return WindowDeduplicationStrategy(max_window=50)


@pytest.fixture()
def make_envelope():
    """Factory fixture for ContentEnvelope instances."""

    def _factory(
        content: str = "test content for dedup adapter",
        content_type: ContentType = ContentType.TEXT,
        metadata: dict | None = None,
    ) -> ContentEnvelope:
        return ContentEnvelope(
            content=content,
            content_type=content_type,
            metadata=metadata or {},
        )

    return _factory


@pytest.fixture()
def make_session():
    """Factory fixture for SessionContext instances."""

    def _factory(session_id: str = "test-session-001") -> SessionContext:
        return SessionContext(session_id=session_id)

    return _factory


class TestWindowDedupContract(DeduplicationStrategyContract):
    """WindowDeduplicationStrategy must satisfy the DeduplicationStrategy contract."""


class TestWindowDedupSpecific:
    """Window-based dedup specific behavioral tests."""

    def test_first_call_not_duplicate(self, dedup_strategy, make_envelope, make_session):
        """First call for any content is never a duplicate."""
        session = make_session()
        envelope = make_envelope(content="some unique content here for testing")
        assert dedup_strategy.is_duplicate(envelope, session) is False

    def test_identical_second_call_is_duplicate(self, dedup_strategy, make_envelope, make_session):
        """Second call with identical content IS a duplicate."""
        session = make_session()
        content = "x" * 150  # over min_content_length
        envelope = make_envelope(content=content)
        assert dedup_strategy.is_duplicate(envelope, session) is False
        assert dedup_strategy.is_duplicate(envelope, session) is True

    def test_different_content_not_duplicate(self, dedup_strategy, make_envelope, make_session):
        """Different content is not a duplicate."""
        session = make_session()
        env1 = make_envelope(content="a" * 150)
        env2 = make_envelope(content="b" * 150)
        assert dedup_strategy.is_duplicate(env1, session) is False
        assert dedup_strategy.is_duplicate(env2, session) is False

    def test_cross_tool_dedup_via_content_hash(self, dedup_strategy, make_envelope, make_session):
        """Same content from different tools is detected as duplicate (content-based hash)."""
        session = make_session()
        content = "identical content across tools " * 10
        env1 = make_envelope(content=content, metadata={"tool_name": "read_file"})
        env2 = make_envelope(content=content, metadata={"tool_name": "search"})
        assert dedup_strategy.is_duplicate(env1, session) is False
        assert dedup_strategy.is_duplicate(env2, session) is True

    def test_window_eviction_after_max_window(self, make_envelope, make_session):
        """After max_window unique calls, oldest entries are evicted."""
        dedup = WindowDeduplicationStrategy(max_window=3)
        session = make_session()

        # Fill the window with 3 unique entries
        for i in range(3):
            env = make_envelope(content=f"unique content number {i} " * 10)
            dedup.is_duplicate(env, session)

        # The first entry should be evicted after adding a 4th
        env_new = make_envelope(content="brand new content number 4 " * 10)
        dedup.is_duplicate(env_new, session)

        # Now the first entry should no longer be in the window
        env_first = make_envelope(content="unique content number 0 " * 10)
        assert dedup.is_duplicate(env_first, session) is False

    def test_get_reference_returns_backreference(self, dedup_strategy, make_envelope, make_session):
        """get_reference() returns a backreference string with position info."""
        session = make_session()
        content = "some repeated tool output " * 10
        envelope = make_envelope(content=content)
        # First call to populate buffer
        dedup_strategy.is_duplicate(envelope, session)
        # Now get the reference
        ref = dedup_strategy.get_reference(envelope, session)
        assert isinstance(ref, str)
        assert "call #" in ref.lower() or "call #" in ref

    def test_short_content_bypasses_dedup(self, dedup_strategy, make_envelope, make_session):
        """Content shorter than min_content_length always returns False (no duplicate)."""
        session = make_session()
        short = "short"  # 5 chars < 100 default
        envelope = make_envelope(content=short)
        assert dedup_strategy.is_duplicate(envelope, session) is False
        # Even identical second call bypasses
        assert dedup_strategy.is_duplicate(envelope, session) is False

    def test_sha256_hash_used(self, dedup_strategy, make_envelope, make_session):
        """Different content with same length produces different hashes (no collision)."""
        session = make_session()
        env1 = make_envelope(content="a" * 200)
        env2 = make_envelope(content="b" * 200)
        assert dedup_strategy.is_duplicate(env1, session) is False
        assert dedup_strategy.is_duplicate(env2, session) is False

    def test_bounded_deque_maxlen(self):
        """Internal buffer uses deque with maxlen constraint."""
        dedup = WindowDeduplicationStrategy(max_window=50)
        assert dedup._buffer.maxlen == 50

    def test_configurable_max_window(self):
        """max_window can be set via constructor."""
        dedup = WindowDeduplicationStrategy(max_window=10)
        assert dedup._buffer.maxlen == 10

    def test_configurable_min_content_length(self):
        """min_content_length can be set via constructor."""
        dedup = WindowDeduplicationStrategy(min_content_length=200)
        assert dedup._min_content_length == 200

    def test_default_min_content_length(self):
        """Default min_content_length is 100."""
        dedup = WindowDeduplicationStrategy()
        assert dedup._min_content_length == 100

    def test_default_max_window(self):
        """Default max_window is 50."""
        dedup = WindowDeduplicationStrategy()
        assert dedup._buffer.maxlen == 50

    def test_dedup_state_per_strategy_instance(self, make_envelope, make_session):
        """Dedup state is per-strategy-instance, not shared."""
        session = make_session()
        content = "shared content across instances " * 10
        dedup1 = WindowDeduplicationStrategy(max_window=50)
        dedup2 = WindowDeduplicationStrategy(max_window=50)
        env = make_envelope(content=content)
        dedup1.is_duplicate(env, session)
        # dedup2 has its own buffer, so same content is NOT a duplicate
        assert dedup2.is_duplicate(env, session) is False

    def test_get_reference_for_unknown_content(self, dedup_strategy, make_envelope, make_session):
        """get_reference() for never-seen content returns a generic reference."""
        session = make_session()
        envelope = make_envelope(content="never seen before " * 10)
        ref = dedup_strategy.get_reference(envelope, session)
        assert isinstance(ref, str)
        assert len(ref) > 0


class TestWindowDedupCallOrderBackreference:
    """Finding 4: backreferences must use monotonic call order, not deque position."""

    def test_backreference_uses_stable_call_number(self, make_envelope, make_session):
        """After inserting A, B, C, A's reference should say call #1 not shift."""
        dedup = WindowDeduplicationStrategy(max_window=50)
        session = make_session()
        env_a = make_envelope(content="content A repeated " * 10)
        env_b = make_envelope(content="content B repeated " * 10)
        env_c = make_envelope(content="content C repeated " * 10)
        # A is call #1, B is call #2, C is call #3
        dedup.is_duplicate(env_a, session)
        dedup.is_duplicate(env_b, session)
        dedup.is_duplicate(env_c, session)
        ref_a = dedup.get_reference(env_a, session)
        ref_b = dedup.get_reference(env_b, session)
        # A should always be call #1, B should always be call #2
        assert "call #1" in ref_a
        assert "call #2" in ref_b

    def test_duplicate_hit_refreshes_buffer_entry(self, make_envelope, make_session):
        """Duplicate content should be refreshed in the window to prevent eviction."""
        dedup = WindowDeduplicationStrategy(max_window=5)
        session = make_session()
        env_target = make_envelope(content="target content to keep " * 10)
        # Insert target as call #1
        dedup.is_duplicate(env_target, session)
        # Fill buffer with 4 more unique items (calls #2-5)
        for i in range(4):
            env = make_envelope(content=f"filler content number {i} " * 10)
            dedup.is_duplicate(env, session)
        # Hit target again as duplicate -- should refresh it in the window
        assert dedup.is_duplicate(env_target, session) is True
        # Now add 4 more unique items (calls #7-10), would evict if not refreshed
        for i in range(4):
            env = make_envelope(content=f"new filler content {i} " * 10)
            dedup.is_duplicate(env, session)
        # Target should still be in the window due to refresh
        assert dedup.is_duplicate(env_target, session) is True
