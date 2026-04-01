"""Tests for SemanticDiffStrategy."""

from __future__ import annotations

import pytest

from token_sieve.adapters.cache.diff_state_store import DiffStateStore
from token_sieve.adapters.compression.semantic_diff import SemanticDiffStrategy
from token_sieve.domain.model import ContentEnvelope, ContentType
from tests.unit.adapters.conftest import CompressionStrategyContract


class TestSemanticDiffContract(CompressionStrategyContract):
    """SemanticDiffStrategy must pass CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self) -> SemanticDiffStrategy:
        store = DiffStateStore()
        return SemanticDiffStrategy(store=store)


class TestFirstCall:
    """First call stores result and returns full content."""

    def test_first_call_returns_full_content(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="line 1\nline 2\nline 3",
            content_type=ContentType.TEXT,
            metadata=(("source_tool", "read_file"), ("source_args", '{"path": "a"}')),
        )
        result = strategy.compress(envelope)
        assert result.content == "line 1\nline 2\nline 3"

    def test_first_call_stores_in_diff_state(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="hello",
            content_type=ContentType.TEXT,
            metadata=(("source_tool", "read_file"), ("source_args", '{"path": "a"}')),
        )
        strategy.compress(envelope)
        assert store.get_previous("read_file", {"path": "a"}) == "hello"


class TestSameContent:
    """Second call with same content returns no-changes message."""

    def test_same_content_returns_no_changes(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="unchanged",
            content_type=ContentType.TEXT,
            metadata=(("source_tool", "read_file"), ("source_args", '{"path": "a"}')),
        )
        strategy.compress(envelope)
        result = strategy.compress(envelope)
        assert "[No changes since last read]" in result.content


class TestChangedContent:
    """Second call with changed content returns human-readable diff."""

    def test_changed_content_returns_diff(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        meta = (("source_tool", "read_file"), ("source_args", '{"path": "a"}'))
        env1 = ContentEnvelope(
            content="line 1\nline 2\nline 3",
            content_type=ContentType.TEXT,
            metadata=meta,
        )
        strategy.compress(env1)
        env2 = ContentEnvelope(
            content="line 1\nline 2 modified\nline 3\nline 4",
            content_type=ContentType.TEXT,
            metadata=meta,
        )
        result = strategy.compress(env2)
        # Should contain some diff indicators
        assert "Added:" in result.content or "Removed:" in result.content or "Changed:" in result.content


class TestCanHandle:
    """can_handle() checks for source_tool metadata."""

    def test_can_handle_with_source_tool(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="test",
            content_type=ContentType.TEXT,
            metadata=(("source_tool", "read_file"),),
        )
        assert strategy.can_handle(envelope) is True

    def test_cannot_handle_without_source_tool(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="test",
            content_type=ContentType.TEXT,
        )
        assert strategy.can_handle(envelope) is False

    def test_cannot_handle_non_text(self) -> None:
        store = DiffStateStore()
        strategy = SemanticDiffStrategy(store=store)
        envelope = ContentEnvelope(
            content="binary data",
            content_type=ContentType.BINARY,
            metadata=(("source_tool", "read_file"),),
        )
        assert strategy.can_handle(envelope) is False
