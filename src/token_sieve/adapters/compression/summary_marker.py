"""Summary marker formatting utility for lossy compression adapters.

Summary markers turn lossy compression into lossless information:
the agent retains awareness of what was removed and can request
the full content if needed.

Format: [token-sieve: {adapter} {original} lines filtered to {kept}{, showing kept_types}]
"""

from __future__ import annotations


def format_summary_marker(
    adapter_name: str,
    original_count: int,
    kept_count: int,
    kept_types: str | None = None,
) -> str:
    """Format a consistent summary marker for lossy adapters.

    Args:
        adapter_name: Name of the adapter (e.g. "LogLevelFilter").
        original_count: Total lines before filtering.
        kept_count: Lines retained after filtering.
        kept_types: Optional description of what was kept (e.g. "ERROR+WARN").

    Returns:
        Single-line bracket-formatted marker string.
    """
    suffix = f", showing {kept_types}" if kept_types else ""
    return (
        f"[token-sieve: {adapter_name} {original_count} lines "
        f"filtered to {kept_count}{suffix}]"
    )
