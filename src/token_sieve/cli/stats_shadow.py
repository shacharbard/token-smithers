"""stats --shadow subcommand — per-pattern shadow sampling drill-down.

Reads shadow_pattern_stats from the learning store and prints a table
sorted by sample_count DESC. Shows: pattern_hash (truncated), adapter_name,
sample_count, mean_savings_pct, retry_count, last_seen.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DEFAULT_LEARNING_DB = os.path.expanduser("~/.token-sieve/learning.db")


def run_stats_shadow(db_path: str | None = None) -> int:
    """Print per-pattern shadow sampling drill-down table to stdout.

    Args:
        db_path: Path to the learning SQLite DB. Defaults to
            TOKEN_SIEVE_LEARNING_DB env var or ~/.token-sieve/learning.db.

    Returns:
        0 on success.
    """
    if db_path is None:
        db_path = os.environ.get("TOKEN_SIEVE_LEARNING_DB", _DEFAULT_LEARNING_DB)

    if not Path(db_path).exists():
        print("No shadow data yet — no learning DB found at:", db_path)
        return 0

    try:
        conn = sqlite3.connect(db_path, timeout=1)
        rows = conn.execute(
            """\
            SELECT
                pattern_hash,
                adapter_name,
                sample_count,
                CASE
                    WHEN raw_bytes_sum > 0
                    THEN ROUND((1.0 - CAST(compressed_bytes_sum AS REAL) / raw_bytes_sum) * 100, 1)
                    ELSE 0.0
                END AS mean_savings_pct,
                retry_count,
                last_seen
            FROM shadow_pattern_stats
            ORDER BY sample_count DESC
            """
        ).fetchall()
        conn.close()
    except Exception as exc:
        print(f"No shadow data yet — could not query DB: {exc}")
        return 0

    if not rows:
        print("No shadow data yet — shadow_pattern_stats table is empty.")
        return 0

    # Header
    hash_w = 16
    adp_w = 20
    cnt_w = 8
    sav_w = 10
    ret_w = 8
    ts_w = 26

    header = (
        f"  {'Pattern Hash':<{hash_w}} "
        f"{'Adapter':<{adp_w}} "
        f"{'Samples':>{cnt_w}} "
        f"{'Savings%':>{sav_w}} "
        f"{'Retries':>{ret_w}} "
        f"{'Last Seen':<{ts_w}}"
    )
    sep = "  " + "-" * (hash_w + adp_w + cnt_w + sav_w + ret_w + ts_w + 5 * 1)

    print()
    print("  === Shadow Pattern Stats ===")
    print()
    print(header)
    print(sep)

    for pattern_hash, adapter_name, sample_count, mean_savings_pct, retry_count, last_seen in rows:
        # Truncate hash to fit column
        short_hash = pattern_hash[:hash_w] if pattern_hash else "—"
        short_adapter = adapter_name[:adp_w] if adapter_name else "—"
        last_seen_str = (last_seen or "—")[:ts_w]

        print(
            f"  {short_hash:<{hash_w}} "
            f"{short_adapter:<{adp_w}} "
            f"{sample_count:>{cnt_w}} "
            f"{mean_savings_pct:>{sav_w}.1f} "
            f"{retry_count:>{ret_w}} "
            f"{last_seen_str:<{ts_w}}"
        )

    print()
    print(f"  Total patterns: {len(rows)}")
    print()

    return 0
