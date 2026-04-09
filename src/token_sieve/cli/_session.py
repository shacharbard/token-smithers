"""Shared session helpers for CLI subcommands (compress, recall).

Extracted from compress.py and recall.py to avoid duplication.
"""
from __future__ import annotations

import os
import time

# M8 fix: cache a process-unique fallback id so that non-Claude invocations
# (cron, shell scripts, manual CLI runs) do not all collide on the literal
# 'default' string, which poisoned ring-buffer counters and reinforcement
# signals. The cache lives at module scope and is stable within a single
# process but differs across processes (pid + start time).
_FALLBACK_SESSION_ID: str | None = None


def _compute_fallback_session_id() -> str:
    """Build a pid+time stamped fallback session id for a single process."""
    return f"pid-{os.getpid()}-{int(time.time() * 1000)}"


def session_id() -> str:
    """Return CLAUDE_SESSION_ID env var, or a cached process-unique fallback.

    The env var always wins when set. When unset (non-Claude invocation),
    we lazily generate and cache ``pid-<pid>-<ms>``. Subsequent calls in
    the same process return the same cached id so that ring-buffer rows,
    reinforcement events, and retry telemetry stay consistent for a single
    CLI invocation.
    """
    env_sid = os.environ.get("CLAUDE_SESSION_ID")
    if env_sid:
        return env_sid

    global _FALLBACK_SESSION_ID
    if _FALLBACK_SESSION_ID is None:
        _FALLBACK_SESSION_ID = _compute_fallback_session_id()
    return _FALLBACK_SESSION_ID
