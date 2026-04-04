"""Report formatter for `token-sieve stats --full` output.

Queries the SQLite learning DB for telemetry data and formats
it as terminal-friendly table output.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def query_learning_telemetry() -> dict:
    """Query the learning DB for telemetry breakdowns.

    Returns dict with tool_breakdown, adapter_effectiveness,
    cross_server, and suggestions lists. All empty if DB unavailable.
    """
    db_path = os.path.expanduser("~/.token-sieve/learning.db")
    if not Path(db_path).exists():
        return {
            "tool_breakdown": [],
            "adapter_effectiveness": [],
            "cross_server": [],
            "suggestions": [],
        }

    try:
        conn = sqlite3.connect(db_path, timeout=1)

        # Per-tool breakdown
        rows = conn.execute(
            "SELECT tool_name, COUNT(*) as cnt, "
            "SUM(original_tokens) as orig, SUM(compressed_tokens) as comp "
            "FROM compression_events "
            "GROUP BY tool_name ORDER BY (orig - comp) DESC"
        ).fetchall()
        tool_breakdown = [
            {
                "tool_name": r[0],
                "event_count": r[1],
                "total_original": r[2],
                "total_compressed": r[3],
                "total_saved": r[2] - r[3],
            }
            for r in rows
        ]

        # Adapter effectiveness
        rows = conn.execute(
            "SELECT strategy_name, COUNT(*) as cnt, "
            "SUM(original_tokens) as orig, SUM(compressed_tokens) as comp "
            "FROM compression_events "
            "GROUP BY strategy_name ORDER BY (orig - comp) DESC LIMIT 10"
        ).fetchall()
        adapter_effectiveness = [
            {
                "strategy_name": r[0],
                "event_count": r[1],
                "total_original": r[2],
                "total_compressed": r[3],
                "total_saved": r[2] - r[3],
            }
            for r in rows
        ]

        # Cross-server (same as tool breakdown for now)
        cross_server = tool_breakdown

        conn.close()
        return {
            "tool_breakdown": tool_breakdown,
            "adapter_effectiveness": adapter_effectiveness,
            "cross_server": cross_server,
            "suggestions": [],
        }
    except Exception:
        return {
            "tool_breakdown": [],
            "adapter_effectiveness": [],
            "cross_server": [],
            "suggestions": [],
        }


def format_full_report(telemetry: dict) -> str:
    """Format telemetry data as terminal-friendly tables.

    Returns multi-line string ready for printing.
    """
    lines: list[str] = []

    tool_breakdown = telemetry.get("tool_breakdown", [])
    if tool_breakdown:
        lines.append("  === Per-Tool Breakdown ===")
        lines.append(
            f"  {'Tool':<30} {'Events':>6} {'Original':>10} {'Compressed':>10} {'Saved':>10}"
        )
        lines.append(f"  {'-' * 30} {'-' * 6} {'-' * 10} {'-' * 10} {'-' * 10}")
        for t in tool_breakdown:
            lines.append(
                f"  {t['tool_name']:<30} {t['event_count']:>6} "
                f"{t['total_original']:>10} {t['total_compressed']:>10} "
                f"{t['total_saved']:>10}"
            )
        lines.append("")

    adapters = telemetry.get("adapter_effectiveness", [])
    if adapters:
        lines.append("  === Adapter Effectiveness ===")
        lines.append(
            f"  {'Strategy':<30} {'Events':>6} {'Total Saved':>10}"
        )
        lines.append(f"  {'-' * 30} {'-' * 6} {'-' * 10}")
        for a in adapters:
            lines.append(
                f"  {a['strategy_name']:<30} {a['event_count']:>6} "
                f"{a['total_saved']:>10}"
            )
        lines.append("")

    cross_server = telemetry.get("cross_server", [])
    if cross_server:
        lines.append("  === Cross-Server Comparison ===")
        lines.append(
            f"  {'Tool':<30} {'Events':>6} {'Saved':>10}"
        )
        lines.append(f"  {'-' * 30} {'-' * 6} {'-' * 10}")
        for c in cross_server:
            lines.append(
                f"  {c['tool_name']:<30} {c['event_count']:>6} "
                f"{c['total_saved']:>10}"
            )
        lines.append("")

    suggestions = telemetry.get("suggestions", [])
    if suggestions:
        lines.append("  === CLAUDE.md Suggestions ===")
        for s in suggestions:
            lines.append(f"  - {s['suggestion']}")
        lines.append("")

    return "\n".join(lines)
