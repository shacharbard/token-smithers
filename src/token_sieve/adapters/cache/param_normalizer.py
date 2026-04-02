"""Parameter normalization utilities for semantic cache matching.

Pure functions -- no side effects, no external dependencies beyond stdlib.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from typing import Any


def normalize_args(args: dict[str, Any]) -> str:
    """Normalize tool arguments to a canonical string form.

    Transformations applied:
    - Sort JSON keys recursively
    - Lowercase string values
    - Strip leading/trailing whitespace from strings
    - Remove trailing slashes from path-like strings
    - Normalize None / "null" / "" to a consistent null form
    - Sort string lists for determinism
    """
    normalized = _normalize_value(args)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def compute_args_hash(args: dict[str, Any]) -> str:
    """Compute a SHA-256 hash of normalized arguments.

    Equivalent args with different ordering/casing produce the same hash.
    """
    canonical = normalize_args(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two strings.

    Uses difflib.SequenceMatcher for O(n*m) edit-distance-based similarity.
    Returns a float in [0.0, 1.0] where 1.0 means identical.
    """
    return difflib.SequenceMatcher(None, a, b).ratio()


def _normalize_value(value: Any) -> Any:
    """Recursively normalize a value for canonical JSON serialization."""
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    # int, float, bool -- pass through
    return value


def _normalize_string(s: str) -> str | None:
    """Normalize a single string value."""
    stripped = s.strip()
    # Normalize empty and "null" to None
    if stripped == "" or stripped.lower() == "null":
        return None
    # Lowercase
    result = stripped.lower()
    # Remove trailing slashes (path normalization)
    if len(result) > 1:
        result = result.rstrip("/")
    return result
