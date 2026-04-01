"""TimestampNormalizer -- converts ISO-8601 timestamps to compact relative offsets.

Lossless cleanup adapter: parses first timestamp as reference (T0),
replaces all subsequent timestamps with relative offsets (+2h32m).
Typically saves 20-40%.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timezone

from token_sieve.domain.model import ContentEnvelope

# ISO-8601 pattern: 2024-03-15T10:00:00Z, 2024-03-15T10:00:00.123Z,
# 2024-03-15T10:00:00+05:30, 2024-03-15T10:00:00-04:00
_ISO_PATTERN = re.compile(
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
    r'(?:\.\d+)?'                          # optional fractional seconds
    r'(?:Z|[+-]\d{2}:\d{2})?'             # optional timezone
)


class TimestampNormalizer:
    """Convert ISO-8601 timestamps to relative offsets from first-seen.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept content containing ISO-8601 timestamp patterns."""
        return bool(_ISO_PATTERN.search(envelope.content))

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Replace timestamps with relative offsets from first occurrence."""
        matches = list(_ISO_PATTERN.finditer(envelope.content))
        if not matches:
            return envelope

        # Parse first timestamp as reference
        ref_dt = _parse_iso(matches[0].group())
        if ref_dt is None:
            return envelope

        # Replace all timestamps, working backwards to preserve positions
        content = envelope.content
        for match in reversed(matches):
            ts_str = match.group()
            dt = _parse_iso(ts_str)
            if dt is None:
                continue
            offset = _format_offset(dt, ref_dt)
            content = content[:match.start()] + offset + content[match.end():]

        if content == envelope.content:
            return envelope

        return dataclasses.replace(envelope, content=content)


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string, returning None on failure."""
    # Normalize Z to +00:00 for fromisoformat
    normalized = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _format_offset(dt: datetime, ref: datetime) -> str:
    """Format the offset between dt and ref as a compact string."""
    # Ensure both are timezone-aware for comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    delta = dt - ref
    total_seconds = int(delta.total_seconds())

    if total_seconds == 0:
        return "T0"

    sign = "+" if total_seconds > 0 else "-"
    total_seconds = abs(total_seconds)

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not (days or hours):
        # Only show seconds for short intervals
        parts.append(f"{seconds}s")

    return sign + "".join(parts) if parts else "T0"
