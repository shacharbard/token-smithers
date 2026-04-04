"""Tests for CLAUDE.md suggestion generation from learning store data.

Verifies that repeated tool calls and file reads generate
actionable suggestions for CLAUDE.md documentation.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


@pytest.fixture()
async def store():
    """Provide SQLiteLearningStore with in-memory DB."""
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    store = await SQLiteLearningStore.connect(":memory:")
    yield store
    await store.close()


async def _insert_events(
    store,
    session_id: str,
    tool_name: str,
    strategy_name: str,
    original: int,
    compressed: int,
    count: int = 1,
) -> None:
    """Insert multiple compression events."""
    for _ in range(count):
        event = CompressionEvent(
            original_tokens=original,
            compressed_tokens=compressed,
            strategy_name=strategy_name,
            content_type=ContentType.JSON,
        )
        await store.record_compression_event(session_id, event, tool_name)


class TestSuggestRepeatedToolCalls:
    """Tests for repeated tool call suggestions."""

    @pytest.mark.asyncio
    async def test_suggest_repeated_tool_calls(self, store) -> None:
        """Tool called 5+ times generates suggestion."""
        # Insert 5 events for same tool in same session
        await _insert_events(store, "s1", "read_file", "whitespace", 1000, 600, count=5)

        suggestions = await store.get_suggestion_candidates("s1")

        repeated = [s for s in suggestions if s["type"] == "repeated_tool"]
        assert len(repeated) >= 1
        assert repeated[0]["target"] == "read_file"
        assert repeated[0]["count"] >= 5
        assert "CLAUDE.md" in repeated[0]["suggestion"]

    @pytest.mark.asyncio
    async def test_no_suggestions_below_threshold(self, store) -> None:
        """3 calls doesn't trigger a suggestion."""
        await _insert_events(store, "s1", "read_file", "ws", 100, 50, count=3)

        suggestions = await store.get_suggestion_candidates("s1")

        repeated = [s for s in suggestions if s["type"] == "repeated_tool"]
        assert len(repeated) == 0


class TestSuggestRepeatedFileReads:
    """Tests for repeated file/content read suggestions."""

    @pytest.mark.asyncio
    async def test_suggest_repeated_file_reads(self, store) -> None:
        """Same tool+strategy compressed 4+ times generates suggestion."""
        # 4 events with same tool and strategy = repeated content pattern
        await _insert_events(store, "s1", "read_file", "whitespace", 500, 300, count=4)

        suggestions = await store.get_suggestion_candidates("s1")

        content = [s for s in suggestions if s["type"] == "repeated_content"]
        assert len(content) >= 1
        assert "CLAUDE.md" in content[0]["suggestion"]


class TestSuggestionsInReport:
    """Tests for suggestions appearing in session report."""

    @pytest.mark.asyncio
    async def test_suggestions_included_in_report(self, store) -> None:
        """Suggestions appear via get_suggestion_candidates called separately."""
        await _insert_events(store, "s1", "list_files", "ws", 200, 100, count=6)

        suggestions = await store.get_suggestion_candidates("s1")
        assert len(suggestions) > 0

        # Verify each suggestion has required fields
        for s in suggestions:
            assert "type" in s
            assert "target" in s
            assert "count" in s
            assert "suggestion" in s
