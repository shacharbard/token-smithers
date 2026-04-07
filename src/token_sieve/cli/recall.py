"""recall CLI subcommand — print Nth-most-recent raw output from the ring buffer.

Usage:
    token-sieve recall [N]   # N defaults to 1 (most recent)

Decision D5b: ring buffer stores last 10 raw outputs per session; recall reads
them back for manual inspection without needing the compressed MCP output.
"""
from __future__ import annotations

import os
import sys


def _session_id() -> str:
    """Return CLAUDE_SESSION_ID env var or 'default' if unset."""
    return os.environ.get("CLAUDE_SESSION_ID", "default")


def _get_ring_buffer():
    """Return a RingBuffer instance keyed to the current session.

    Extracted as a module-level factory so tests can monkeypatch it.
    """
    from token_sieve.adapters.learning.ring_buffer import RingBuffer

    return RingBuffer(session_id=_session_id())


def run(argv: list[str]) -> int:
    """Run the recall subcommand.

    Prints the Nth-most-recent raw (pre-compression) output stored in the
    ring buffer for the current session.

    Args:
        argv: Optional positional argument — integer N >= 1 (default 1).

    Returns:
        0 on success, 1 if index is out of range, 2 if N is invalid.
    """
    # Parse optional index argument
    n = 1
    if argv:
        raw_n = argv[0]
        try:
            n = int(raw_n)
        except ValueError:
            print(
                f"Error: invalid index '{raw_n}' — must be an integer >= 1",
                file=sys.stderr,
            )
            return 2

        if n < 1:
            print(
                f"Error: index must be >= 1, got {n}",
                file=sys.stderr,
            )
            return 2

    buf = _get_ring_buffer()

    try:
        output = buf.get(n)
    except IndexError:
        print("Error: no recorded outputs in ring buffer for this session", file=sys.stderr)
        return 1

    sys.stdout.write(output)
    if output and not output.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    return 0
