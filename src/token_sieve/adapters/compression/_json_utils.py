"""Shared JSON parsing utilities for compression adapters."""
from __future__ import annotations

import json
import re
from typing import Any

JSON_START_RE = re.compile(r"^\s*[\[{]")


def try_parse_json(content: str) -> Any | None:
    """Parse JSON content, returning None on failure.

    Catches JSONDecodeError, ValueError, and TypeError consistently.
    """
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
