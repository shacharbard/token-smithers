"""Tests for summary marker formatting utility.

Summary markers turn lossy compression into lossless information --
the agent knows what was removed.
"""

from __future__ import annotations

import pytest

from token_sieve.adapters.compression.summary_marker import format_summary_marker


class TestFormatSummaryMarker:
    """Tests for format_summary_marker()."""

    def test_basic_format_with_counts(self):
        """Marker includes adapter name and line counts."""
        result = format_summary_marker(
            adapter_name="LogLevelFilter",
            original_count=100,
            kept_count=15,
        )
        assert "LogLevelFilter" in result
        assert "100" in result
        assert "15" in result

    def test_bracket_format(self):
        """Marker uses consistent [token-sieve: ...] bracket format."""
        result = format_summary_marker(
            adapter_name="ErrorStackCompressor",
            original_count=50,
            kept_count=5,
        )
        assert result.startswith("[token-sieve:")
        assert result.endswith("]")

    def test_includes_kept_types_when_provided(self):
        """When kept_types is given, it appears in the marker."""
        result = format_summary_marker(
            adapter_name="LogLevelFilter",
            original_count=200,
            kept_count=30,
            kept_types="ERROR+WARN",
        )
        assert "ERROR+WARN" in result

    def test_no_kept_types_omitted(self):
        """When kept_types is None, no extra suffix appears."""
        result = format_summary_marker(
            adapter_name="CodeCommentStripper",
            original_count=80,
            kept_count=60,
        )
        assert "showing" not in result.lower()

    def test_marker_is_single_line(self):
        """Summary marker must be a single line (no newlines)."""
        result = format_summary_marker(
            adapter_name="LogLevelFilter",
            original_count=1000,
            kept_count=50,
            kept_types="ERROR+WARN",
        )
        assert "\n" not in result

    def test_consistent_format_across_adapters(self):
        """All adapters produce the same bracket format prefix."""
        names = ["LogLevelFilter", "ErrorStackCompressor", "CodeCommentStripper"]
        for name in names:
            result = format_summary_marker(
                adapter_name=name,
                original_count=100,
                kept_count=10,
            )
            assert result.startswith("[token-sieve:")
            assert result.endswith("]")

    def test_format_with_zero_kept(self):
        """Edge case: all lines filtered out."""
        result = format_summary_marker(
            adapter_name="LogLevelFilter",
            original_count=50,
            kept_count=0,
        )
        assert "50" in result
        assert "0" in result

    def test_format_with_equal_counts(self):
        """Edge case: no lines actually filtered."""
        result = format_summary_marker(
            adapter_name="CodeCommentStripper",
            original_count=30,
            kept_count=30,
        )
        assert "30" in result
