"""Tests for SmartTruncation adapter (head+tail with omission marker)."""

from __future__ import annotations

import pytest

from token_sieve.adapters.compression.smart_truncation import SmartTruncation
from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------
class TestSmartTruncationContract(CompressionStrategyContract):
    """SmartTruncation must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        return SmartTruncation()


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------
class TestSmartTruncationSpecific:
    """SmartTruncation-specific behavioral tests."""

    def _make_lines(self, n: int) -> str:
        """Generate n lines of content."""
        return "\n".join(f"line {i+1}: content here" for i in range(n))

    def test_long_content_truncated_with_marker(self):
        """Content exceeding head+tail lines gets truncated with marker."""
        content = self._make_lines(200)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=50, tail_lines=20)

        result = strategy.compress(envelope)
        lines = result.content.split("\n")

        # Should have head + marker + tail lines
        assert len(lines) < 200
        # Marker should be present
        assert any("lines omitted" in line for line in lines)

    def test_short_content_unchanged(self):
        """Content within head+tail limit is returned unchanged."""
        content = self._make_lines(30)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=50, tail_lines=20)

        result = strategy.compress(envelope)
        assert result.content == content

    def test_exactly_head_plus_tail_unchanged(self):
        """Content with exactly head+tail lines is not truncated."""
        content = self._make_lines(70)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=50, tail_lines=20)

        result = strategy.compress(envelope)
        assert result.content == content

    def test_single_line_unchanged(self):
        """Single-line content is returned unchanged."""
        envelope = ContentEnvelope(content="one line only", content_type=ContentType.TEXT)
        strategy = SmartTruncation()

        result = strategy.compress(envelope)
        assert result.content == "one line only"

    def test_configurable_head_tail(self):
        """Custom head_lines and tail_lines are respected."""
        content = self._make_lines(100)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=10, tail_lines=5)

        result = strategy.compress(envelope)
        lines = result.content.split("\n")

        # First 10 lines should be from head
        for i in range(10):
            assert lines[i] == f"line {i+1}: content here"

        # Last 5 lines should be from tail
        for i in range(5):
            expected_line_num = 100 - 4 + i
            assert lines[-(5-i)] == f"line {expected_line_num}: content here"

    def test_omission_marker_shows_count(self):
        """Omission marker shows the number of omitted lines."""
        content = self._make_lines(100)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=10, tail_lines=5)

        result = strategy.compress(envelope)
        # 100 - 10 - 5 = 85 lines omitted
        assert "85 lines omitted" in result.content

    def test_default_head_tail_values(self):
        """Default head_lines=50 and tail_lines=20."""
        strategy = SmartTruncation()
        assert strategy.head_lines == 50
        assert strategy.tail_lines == 20

    def test_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        content = self._make_lines(200)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=10, tail_lines=5)

        result = strategy.compress(envelope)
        assert result.content_type == ContentType.TEXT

    def test_can_handle_always_true(self):
        """SmartTruncation is a universal fallback, always handles."""
        envelope = ContentEnvelope(content="anything", content_type=ContentType.TEXT)
        strategy = SmartTruncation()
        assert strategy.can_handle(envelope) is True

    def test_head_preserves_first_lines(self):
        """First head_lines lines are preserved exactly."""
        content = self._make_lines(200)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=50, tail_lines=20)

        result = strategy.compress(envelope)
        result_lines = result.content.split("\n")

        for i in range(50):
            assert result_lines[i] == f"line {i+1}: content here"

    def test_tail_preserves_last_lines(self):
        """Last tail_lines lines are preserved exactly."""
        content = self._make_lines(200)
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = SmartTruncation(head_lines=50, tail_lines=20)

        result = strategy.compress(envelope)
        result_lines = result.content.split("\n")

        for i in range(20):
            expected_line_num = 200 - 19 + i
            assert result_lines[-(20-i)] == f"line {expected_line_num}: content here"
