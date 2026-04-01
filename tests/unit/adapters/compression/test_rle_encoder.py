"""Tests for RunLengthEncoder adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
Verifies run-length encoding of repeated consecutive lines/values.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.rle_encoder import RunLengthEncoder
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide RunLengthEncoder for contract tests."""
    return RunLengthEncoder()


class TestRunLengthEncoderContract(CompressionStrategyContract):
    """RunLengthEncoder must satisfy the CompressionStrategy contract."""


class TestRunLengthEncoderSpecific:
    """RLE-specific behavioral tests."""

    def test_can_handle_with_repeated_lines(self, strategy, make_envelope):
        """Content with 3+ consecutive identical lines is handled."""
        content = "INFO: starting\n" * 5 + "ERROR: failed\n"
        envelope = make_envelope(content=content)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_rejects_no_repeats(self, strategy, make_envelope):
        """Content with no consecutive repeats is rejected."""
        content = "line 1\nline 2\nline 3\nline 4\n"
        envelope = make_envelope(content=content)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_below_threshold(self, strategy, make_envelope):
        """Content with only 2 consecutive repeats (below threshold) is rejected."""
        content = "INFO: ok\nINFO: ok\nERROR: bad\n"
        envelope = make_envelope(content=content)
        assert strategy.can_handle(envelope) is False

    def test_compress_repeated_lines(self, strategy, make_envelope):
        """Repeated consecutive lines are compressed to 'line x N' notation."""
        content = "INFO: ok\nINFO: ok\nINFO: ok\nERROR: bad\n"
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        assert "INFO: ok x3" in result.content
        assert "ERROR: bad" in result.content

    def test_compress_mixed_content(self, strategy, make_envelope):
        """Only repeated groups are compressed; unique lines pass through."""
        lines = (
            ["header"]
            + ["INFO: processing"] * 5
            + ["WARN: slow"]
            + ["DEBUG: tick"] * 4
            + ["footer"]
        )
        content = "\n".join(lines)
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        assert "header" in result.content
        assert "INFO: processing x5" in result.content
        assert "WARN: slow" in result.content
        assert "DEBUG: tick x4" in result.content
        assert "footer" in result.content

    def test_compress_preserves_non_repeated_lines(self, strategy, make_envelope):
        """Lines that appear only once or twice are kept verbatim."""
        content = "a\nb\nc\nc\nc\nd\n"
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        result_lines = result.content.strip().split("\n")
        assert "a" in result_lines
        assert "b" in result_lines
        assert "d" in result_lines
        assert "c x3" in result_lines

    def test_compress_minimum_threshold_three(self, strategy, make_envelope):
        """Groups of exactly 2 are NOT compressed (threshold is 3)."""
        content = "x\nx\ny\ny\ny\n"
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        result_lines = result.content.strip().split("\n")
        # "x" appears twice -- kept as two separate lines
        assert result_lines.count("x") == 2
        # "y" appears three times -- compressed
        assert "y x3" in result_lines

    def test_compress_json_array_with_repeated_values(self, strategy, make_envelope):
        """JSON array with repeated consecutive values is compressed."""
        data = json.dumps(["INFO", "INFO", "INFO", "ERROR", "WARN", "WARN", "WARN"])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        assert "INFO x3" in result.content
        assert "WARN x3" in result.content
        assert "ERROR" in result.content

    def test_compress_log_output_with_repeats(self, strategy, make_envelope):
        """Realistic log output with repeated INFO lines is compressed."""
        lines = [
            "2024-01-01 INFO: Health check OK",
            "2024-01-01 INFO: Health check OK",
            "2024-01-01 INFO: Health check OK",
            "2024-01-01 INFO: Health check OK",
            "2024-01-01 ERROR: Connection refused",
            "2024-01-01 INFO: Retrying...",
        ]
        content = "\n".join(lines)
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        assert "2024-01-01 INFO: Health check OK x4" in result.content
        assert "2024-01-01 ERROR: Connection refused" in result.content
        assert "2024-01-01 INFO: Retrying..." in result.content

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        """compress() preserves the content_type."""
        content = "a\n" * 5
        envelope = make_envelope(content=content, content_type=ContentType.CLI_OUTPUT)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.CLI_OUTPUT

    def test_compress_large_repeat_block(self, strategy, make_envelope):
        """Large repeat block (47 repeats) achieves significant savings."""
        content = "INFO: heartbeat\n" * 47 + "ERROR: timeout\n"
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)

        assert "INFO: heartbeat x47" in result.content
        original_size = len(content)
        compressed_size = len(result.content)
        savings = 1.0 - (compressed_size / original_size)
        assert savings >= 0.50, f"Expected >= 50% savings, got {savings:.1%}"

    def test_compress_does_not_modify_content_without_repeats(self, strategy, make_envelope):
        """If no repeats meet threshold, content is returned unchanged."""
        content = "a\nb\nc\nd\ne\n"
        envelope = make_envelope(content=content)
        # can_handle should be False for no repeats, but if compress is called
        # anyway it should return unchanged
        result = strategy.compress(envelope)
        assert result.content == content
