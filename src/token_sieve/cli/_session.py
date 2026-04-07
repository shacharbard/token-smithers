"""Shared session helpers for CLI subcommands (compress, recall).

Extracted from compress.py and recall.py to avoid duplication.
"""
from __future__ import annotations

import os


def session_id() -> str:
    """Return CLAUDE_SESSION_ID env var or 'default' if unset."""
    return os.environ.get("CLAUDE_SESSION_ID", "default")
