"""Stderr metrics sink for observability.

Formats and emits [token-sieve] log lines to stderr so Claude Code
(or any MCP host) can surface compression stats without polluting
the MCP JSON-RPC stdout channel.
"""
from __future__ import annotations

import sys

from token_sieve.domain.model import CompressionEvent


class StderrMetricsSink:
    """Formats compression metrics and writes them to stderr.

    All public format_* methods return a string; emit() writes to stderr.
    Pure formatting + stderr write — no side effects beyond I/O.
    """

    def format_event(self, event: CompressionEvent, tool_name: str) -> str:
        """Format a single compression event into a log line.

        Example::

            [token-sieve] tools/call read_file: 1000->300 tokens (70% reduction, TruncationCompressor)
        """
        ratio_pct = int(event.savings_ratio * 100)
        return (
            f"[token-sieve] tools/call {tool_name}: "
            f"{event.original_tokens}->{event.compressed_tokens} tokens "
            f"({ratio_pct}% reduction, {event.strategy_name})"
        )

    def format_dedup_hit(self, tool_name: str, position: int) -> str:
        """Format a deduplication hit into a log line.

        Example::

            [token-sieve] tools/call read_file: DEDUP hit (call #3)
        """
        return (
            f"[token-sieve] tools/call {tool_name}: "
            f"DEDUP hit (call #{position})"
        )

    def format_session_summary(
        self, calls: int, original: int, compressed: int
    ) -> str:
        """Format a session summary into a log line.

        Example::

            [token-sieve] session: 10 calls, 5000->2000 tokens
        """
        return (
            f"[token-sieve] session: {calls} calls, "
            f"{original}->{compressed} tokens"
        )

    def emit(self, message: str) -> None:
        """Write a message to stderr with trailing newline."""
        print(message, file=sys.stderr)
