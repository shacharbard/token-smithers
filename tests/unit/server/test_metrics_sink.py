"""Tests for StderrMetricsSink — observability formatter + emitter."""
from __future__ import annotations

import sys
from io import StringIO

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


class TestFormatEvent:
    """format_event produces [token-sieve] formatted log lines."""

    def test_format_event_contains_tool_name(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        event = CompressionEvent(
            original_tokens=1000,
            compressed_tokens=300,
            strategy_name="TruncationCompressor",
            content_type=ContentType.TEXT,
        )
        result = sink.format_event(event, tool_name="read_file")
        assert "[token-sieve]" in result
        assert "read_file" in result

    def test_format_event_contains_token_counts(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        event = CompressionEvent(
            original_tokens=1000,
            compressed_tokens=300,
            strategy_name="TruncationCompressor",
            content_type=ContentType.TEXT,
        )
        result = sink.format_event(event, tool_name="read_file")
        assert "1000" in result
        assert "300" in result

    def test_format_event_contains_reduction_ratio(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        event = CompressionEvent(
            original_tokens=1000,
            compressed_tokens=300,
            strategy_name="TruncationCompressor",
            content_type=ContentType.TEXT,
        )
        result = sink.format_event(event, tool_name="read_file")
        # 70% reduction
        assert "70" in result

    def test_format_event_contains_strategy_name(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        event = CompressionEvent(
            original_tokens=500,
            compressed_tokens=250,
            strategy_name="TruncationCompressor",
            content_type=ContentType.TEXT,
        )
        result = sink.format_event(event, tool_name="echo")
        assert "TruncationCompressor" in result

    def test_format_event_zero_original_tokens(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        event = CompressionEvent(
            original_tokens=0,
            compressed_tokens=0,
            strategy_name="PassthroughStrategy",
            content_type=ContentType.TEXT,
        )
        result = sink.format_event(event, tool_name="echo")
        assert "[token-sieve]" in result
        assert "0%" in result


class TestFormatDedupHit:
    """format_dedup_hit produces dedup-specific log lines."""

    def test_format_dedup_hit_contains_tool_and_position(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        result = sink.format_dedup_hit("read_file", position=3)
        assert "[token-sieve]" in result
        assert "read_file" in result
        assert "DEDUP" in result
        assert "#3" in result


class TestFormatSessionSummary:
    """format_session_summary produces session-level summary lines."""

    def test_format_session_summary(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        result = sink.format_session_summary(
            calls=10, original=5000, compressed=2000
        )
        assert "[token-sieve]" in result
        assert "10" in result
        assert "5000" in result
        assert "2000" in result

    def test_format_session_summary_zero_calls(self) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        result = sink.format_session_summary(
            calls=0, original=0, compressed=0
        )
        assert "[token-sieve]" in result


class TestEmit:
    """emit() writes to stderr."""

    def test_emit_writes_to_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        fake_stderr = StringIO()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        sink.emit("[token-sieve] test message")
        output = fake_stderr.getvalue()
        assert "[token-sieve] test message" in output

    def test_emit_appends_newline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from token_sieve.server.metrics_sink import StderrMetricsSink

        sink = StderrMetricsSink()
        fake_stderr = StringIO()
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        sink.emit("[token-sieve] msg")
        output = fake_stderr.getvalue()
        assert output.endswith("\n")
