"""Config validator -- checks adapter ordering and cross-section constraints.

Advisory validation: returns a list of warning strings, never raises.
Enforces the ordering invariant:
  Cleanup -> Content-specific lossy -> Format transforms -> Safety net (truncation)
Also validates cross-section dependencies (e.g., semantic_cache requires learning).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from token_sieve.config.schema import TokenSieveConfig

# Adapter categories by execution phase
CLEANUP = frozenset({
    "whitespace_normalizer",
    "null_field_elider",
    "path_prefix_deduplicator",
    "timestamp_normalizer",
})

CONTENT_SPECIFIC = frozenset({
    "log_level_filter",
    "error_stack_compressor",
    "code_comment_stripper",
    "json_code_unwrapper",
    "tree_sitter_ast",
})

FORMAT = frozenset({
    "toon_compressor",
    "yaml_transcoder",
    "sentence_scorer",
    "rle_encoder",
})

SAFETY_NET = frozenset({
    "truncation",
})

# Ordered phases: each adapter must appear in or after its phase
_PHASES: list[tuple[str, frozenset[str]]] = [
    ("cleanup", CLEANUP),
    ("content_specific", CONTENT_SPECIFIC),
    ("format", FORMAT),
    ("safety_net", SAFETY_NET),
]


def validate_adapter_order(adapter_names: list[str]) -> list[str]:
    """Validate adapter ordering conventions.

    Returns a list of advisory warning strings. Empty list means valid.
    Unknown adapter names are silently accepted (extensible).
    """
    warnings: list[str] = []

    if not adapter_names:
        return warnings

    # Check for duplicates
    seen: set[str] = set()
    for name in adapter_names:
        if name in seen:
            warnings.append(f"Duplicate adapter: '{name}' appears more than once")
        seen.add(name)

    # Check truncation is last (if present)
    if "truncation" in adapter_names and adapter_names[-1] != "truncation":
        warnings.append(
            "truncation (safety net) should be last in the adapter chain"
        )

    # Check phase ordering: each known adapter should not appear before
    # adapters from an earlier phase
    _check_phase_ordering(adapter_names, warnings)

    return warnings


def _get_phase(name: str) -> int | None:
    """Return the phase index for a known adapter, or None for unknown."""
    for idx, (_phase_name, members) in enumerate(_PHASES):
        if name in members:
            return idx
    return None


def _check_phase_ordering(adapter_names: list[str], warnings: list[str]) -> None:
    """Check that adapters respect phase ordering."""
    max_phase_seen = -1

    for name in adapter_names:
        phase = _get_phase(name)
        if phase is None:
            continue  # Unknown adapter, skip

        if phase < max_phase_seen:
            # This adapter is in an earlier phase than something we already saw
            warnings.append(
                f"'{name}' (phase {_PHASES[phase][0]}) appears after "
                f"adapters from a later phase — cleanup adapters should "
                f"come before content-specific and format transforms"
            )
        else:
            max_phase_seen = phase


def validate_config(config: TokenSieveConfig) -> list[str]:
    """Validate cross-section config constraints.

    Returns a list of error strings. Empty list means valid.
    Checks:
    - semantic_cache.enabled requires learning.enabled (SQLite dependency)
    """
    errors: list[str] = []

    if config.semantic_cache.enabled and not config.learning.enabled:
        errors.append(
            "semantic_cache.enabled=True requires learning.enabled=True "
            "(semantic cache depends on SQLite persistence)"
        )

    return errors
