"""LogLevelFilter -- lossy compression adapter for log output.

Filters log content to retain only ERROR/WARN lines, collapses
consecutive identical messages with [xN] notation, and appends
a summary marker showing what was removed.

Off by default (lossy). Requires explicit ``enabled=True`` opt-in.
"""

from __future__ import annotations

import re

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope

# Pattern: optional timestamp prefix, then a log level keyword
_LOG_LINE_RE = re.compile(
    r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}[.\d]*\s*)?"
    r"(DEBUG|TRACE|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b",
    re.IGNORECASE,
)

_MIN_LOG_LINES = 5  # Decision 11: conservative multi-signal detection


class LogLevelFilter:
    """Filter log output to retained severity levels.

    Satisfies CompressionStrategy protocol structurally.
    Lossy adapter: off by default, opt-in via ``enabled=True``.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        retain_levels: set[str] | None = None,
    ) -> None:
        self._enabled = enabled
        self._retain_levels = {
            level.upper() for level in (retain_levels or {"ERROR", "WARN", "WARNING"})
        }

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True only if enabled AND content looks like logs.

        Conservative detection (Decision 11): requires 5+ lines matching
        the log-level pattern (timestamp? LEVEL message).
        """
        if not self._enabled:
            return False
        lines = envelope.content.split("\n")
        match_count = sum(1 for line in lines if _LOG_LINE_RE.match(line.strip()))
        return match_count >= _MIN_LOG_LINES

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Filter to retained levels, collapse repeats, append summary marker."""
        lines = envelope.content.split("\n")
        original_count = len(lines)

        # Filter to retained levels
        kept_lines: list[str] = []
        for line in lines:
            m = _LOG_LINE_RE.match(line.strip())
            if m and m.group(1).upper() in self._retain_levels:
                kept_lines.append(line)

        # Collapse consecutive identical messages
        collapsed: list[str] = []
        for line in kept_lines:
            # Extract the message part (after level keyword)
            msg = _extract_message(line)
            if collapsed and _extract_message(collapsed[-1].split(" [x")[0]) == msg:
                # Increment repeat count
                prev = collapsed[-1]
                if " [x" in prev:
                    count = int(prev.rsplit("[x", 1)[1].rstrip("]")) + 1
                    collapsed[-1] = prev.rsplit(" [x", 1)[0] + f" [x{count}]"
                else:
                    collapsed[-1] = prev + " [x2]"
            else:
                collapsed.append(line)

        kept_count = len(collapsed)
        kept_types = "+".join(sorted(self._retain_levels))
        marker = format_summary_marker(
            adapter_name="LogLevelFilter",
            original_count=original_count,
            kept_count=kept_count,
            kept_types=kept_types,
        )
        compressed_content = "\n".join(collapsed) + "\n" + marker

        return ContentEnvelope(
            content=compressed_content,
            content_type=envelope.content_type,
            metadata=dict(envelope.metadata),
        )


def _extract_message(line: str) -> str:
    """Extract the message portion after the log level keyword."""
    m = _LOG_LINE_RE.match(line.strip())
    if m:
        # Return everything after the level keyword
        idx = m.end()
        return line.strip()[idx:].strip()
    return line.strip()
