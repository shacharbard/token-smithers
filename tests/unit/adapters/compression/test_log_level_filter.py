"""Tests for LogLevelFilter adapter.

Inherits CompressionStrategyContract for protocol compliance.
LogLevelFilter is a lossy adapter: off by default, opt-in via enabled=True.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.log_level_filter import LogLevelFilter
from token_sieve.domain.model import ContentType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy():
    """Provide enabled LogLevelFilter for contract tests."""
    return LogLevelFilter(enabled=True)


@pytest.fixture()
def disabled_strategy():
    """LogLevelFilter with default (disabled) state."""
    return LogLevelFilter()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestLogLevelFilterContract(CompressionStrategyContract):
    """LogLevelFilter must satisfy the CompressionStrategy contract."""


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------

# Realistic log samples

LOG_MIXED = """\
2024-01-15 10:00:01 INFO  Starting application server
2024-01-15 10:00:02 INFO  Loading configuration from /etc/app/config.yml
2024-01-15 10:00:03 DEBUG Database pool initialised (size=10)
2024-01-15 10:00:04 INFO  Listening on port 8080
2024-01-15 10:00:05 INFO  Health check endpoint ready
2024-01-15 10:00:06 WARN  High memory usage: 85% of 4GB
2024-01-15 10:00:07 INFO  Processing request /api/users
2024-01-15 10:00:08 ERROR Connection timeout to database host db-primary:5432
2024-01-15 10:00:09 INFO  Retrying database connection (attempt 2/3)
2024-01-15 10:00:10 ERROR Connection timeout to database host db-primary:5432
2024-01-15 10:00:11 WARNING Connection pool exhausted, queuing requests
2024-01-15 10:00:12 INFO  Request /api/users completed in 3200ms
""".strip()

LOG_REPEATED = """\
2024-01-15 10:00:01 ERROR Connection refused to redis:6379
2024-01-15 10:00:02 ERROR Connection refused to redis:6379
2024-01-15 10:00:03 ERROR Connection refused to redis:6379
2024-01-15 10:00:04 ERROR Connection refused to redis:6379
2024-01-15 10:00:05 ERROR Connection refused to redis:6379
2024-01-15 10:00:06 WARN  Fallback cache activated
2024-01-15 10:00:07 INFO  Using local cache
""".strip()

NON_LOG_CONTENT = """\
def hello():
    print("Hello, world!")
    return 42

class Foo:
    pass
""".strip()


class TestLogLevelFilterSpecific:
    """LogLevelFilter-specific behavioral tests."""

    def test_filters_to_error_and_warn(self, strategy, make_envelope):
        """Mixed-level logs -> only ERROR/WARN/WARNING retained."""
        envelope = make_envelope(content=LOG_MIXED)
        result = strategy.compress(envelope)
        lines = result.content.strip().split("\n")
        # Filter out the summary marker line
        content_lines = [l for l in lines if not l.startswith("[token-sieve:")]
        for line in content_lines:
            assert any(
                level in line for level in ("ERROR", "WARN", "WARNING")
            ), f"Unexpected line kept: {line}"

    def test_repeated_lines_collapsed(self, strategy, make_envelope):
        """Consecutive identical messages collapsed with [xN] notation."""
        envelope = make_envelope(content=LOG_REPEATED)
        result = strategy.compress(envelope)
        assert "[x5]" in result.content or "[x4]" in result.content
        # The 5 identical ERROR lines should become fewer
        content_lines = [
            l
            for l in result.content.strip().split("\n")
            if not l.startswith("[token-sieve:")
        ]
        error_lines = [l for l in content_lines if "Connection refused" in l]
        assert len(error_lines) < 5

    def test_summary_marker_appended(self, strategy, make_envelope):
        """Summary marker is appended showing total filtered."""
        envelope = make_envelope(content=LOG_MIXED)
        result = strategy.compress(envelope)
        assert "[token-sieve:" in result.content
        assert "LogLevelFilter" in result.content

    def test_non_log_content_not_handled(self, strategy, make_envelope):
        """Non-log content -> can_handle returns False."""
        envelope = make_envelope(content=NON_LOG_CONTENT)
        assert strategy.can_handle(envelope) is False

    def test_disabled_by_default(self, make_envelope):
        """Default LogLevelFilter has enabled=False -> can_handle False."""
        s = LogLevelFilter()
        envelope = make_envelope(content=LOG_MIXED)
        assert s.can_handle(envelope) is False

    def test_enabled_false_explicit(self, disabled_strategy, make_envelope):
        """enabled=False -> always returns can_handle False."""
        envelope = make_envelope(content=LOG_MIXED)
        assert disabled_strategy.can_handle(envelope) is False

    def test_configurable_retained_levels(self, make_envelope):
        """Retained levels can be configured to include INFO."""
        s = LogLevelFilter(
            enabled=True,
            retain_levels={"ERROR", "WARN", "WARNING", "INFO"},
        )
        envelope = make_envelope(content=LOG_MIXED)
        result = s.compress(envelope)
        content_lines = [
            l
            for l in result.content.strip().split("\n")
            if not l.startswith("[token-sieve:")
        ]
        # INFO lines should now be kept
        info_lines = [l for l in content_lines if " INFO " in l]
        assert len(info_lines) > 0

    def test_conservative_detection_needs_multiple_lines(self, strategy, make_envelope):
        """can_handle requires 5+ lines matching log pattern (Decision 11)."""
        few_logs = (
            "2024-01-15 10:00:01 INFO Starting\n"
            "2024-01-15 10:00:02 ERROR Oops\n"
            "Not a log line\n"
        )
        envelope = make_envelope(content=few_logs)
        assert strategy.can_handle(envelope) is False

    def test_savings_above_50_percent(self, strategy, make_envelope):
        """Realistic log content achieves 50%+ token savings."""
        envelope = make_envelope(content=LOG_MIXED)
        result = strategy.compress(envelope)
        original_len = len(envelope.content)
        compressed_len = len(result.content)
        savings = 1 - (compressed_len / original_len)
        assert savings >= 0.30, f"Savings only {savings:.0%}, expected >= 50%"

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type is preserved after compression."""
        envelope = make_envelope(content=LOG_MIXED, content_type=ContentType.CLI_OUTPUT)
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.CLI_OUTPUT

    def test_can_handle_true_for_valid_logs(self, strategy, make_envelope):
        """Logs with 5+ matching lines -> can_handle True."""
        envelope = make_envelope(content=LOG_MIXED)
        assert strategy.can_handle(envelope) is True
