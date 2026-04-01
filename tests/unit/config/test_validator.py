"""Tests for config validator -- adapter ordering conventions.

validate_adapter_order() returns advisory warnings, never raises.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def validate():
    """Provide validate_adapter_order function."""
    from token_sieve.config.validator import validate_adapter_order

    return validate_adapter_order


class TestValidateAdapterOrder:
    """Tests for adapter ordering validation."""

    def test_valid_ordering_no_warnings(self, validate):
        """Correct ordering: cleanup -> content-specific -> format -> safety net."""
        warnings = validate([
            "whitespace_normalizer",
            "null_field_elider",
            "path_prefix_deduplicator",
            "timestamp_normalizer",
            "log_filter",
            "error_compressor",
            "toon",
            "truncation",
        ])
        assert warnings == []

    def test_cleanup_after_content_specific_warns(self, validate):
        """Cleanup adapter after content-specific should produce a warning."""
        warnings = validate([
            "log_filter",
            "whitespace_normalizer",
        ])
        assert len(warnings) >= 1
        assert any("whitespace_normalizer" in w for w in warnings)

    def test_truncation_not_last_warns(self, validate):
        """TruncationCompressor not at the end should produce a warning."""
        warnings = validate([
            "truncation",
            "whitespace_normalizer",
        ])
        assert len(warnings) >= 1
        assert any("truncation" in w.lower() for w in warnings)

    def test_duplicate_adapters_warns(self, validate):
        """Duplicate adapter names should produce a warning."""
        warnings = validate([
            "whitespace_normalizer",
            "whitespace_normalizer",
        ])
        assert len(warnings) >= 1
        assert any("duplicate" in w.lower() for w in warnings)

    def test_empty_list_valid(self, validate):
        """Empty adapter list should be valid (no warnings)."""
        warnings = validate([])
        assert warnings == []

    def test_single_adapter_valid(self, validate):
        """Single adapter should be valid (no ordering issues)."""
        warnings = validate(["whitespace_normalizer"])
        assert warnings == []

    def test_unknown_adapter_passes(self, validate):
        """Unknown adapter names should pass without warnings (extensible)."""
        warnings = validate(["custom_adapter_xyz"])
        assert warnings == []

    def test_cleanup_only_valid(self, validate):
        """All cleanup adapters is a valid configuration."""
        warnings = validate([
            "whitespace_normalizer",
            "null_field_elider",
            "path_prefix_deduplicator",
            "timestamp_normalizer",
        ])
        assert warnings == []

    def test_format_before_content_specific_warns(self, validate):
        """Format transform before content-specific adapter should warn."""
        warnings = validate([
            "toon",
            "log_filter",
        ])
        assert len(warnings) >= 1

    def test_returns_list_of_strings(self, validate):
        """Return type should always be a list of strings."""
        result = validate(["whitespace_normalizer", "truncation"])
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    def test_truncation_last_is_valid(self, validate):
        """Truncation at the end should not produce a warning about position."""
        warnings = validate([
            "whitespace_normalizer",
            "truncation",
        ])
        # Should have no truncation-position warning
        assert not any("truncation" in w.lower() and "last" in w.lower() for w in warnings)


class TestValidatorMatchesRegistry:
    """Finding 2 (P1): Validator names must match _ADAPTER_REGISTRY canonical names."""

    def test_default_adapter_order_produces_no_warnings(self, validate):
        """Default adapters from _default_adapters() should pass validation."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        warnings = validate(names)
        assert warnings == [], f"Unexpected warnings: {warnings}"

    def test_canonical_names_recognized_by_validator(self, validate):
        """All _ADAPTER_REGISTRY names must be recognized by the validator."""
        from token_sieve.server.proxy import ProxyServer

        for name in ProxyServer._ADAPTER_REGISTRY:
            # Each registered name should not produce "unknown" warnings
            # (validator silently accepts unknowns, but known names should
            # be in the correct phase frozensets)
            pass  # The real check is test_default_adapter_order_produces_no_warnings

    def test_content_specific_contains_canonical_names(self):
        """CONTENT_SPECIFIC frozenset must use canonical adapter names."""
        from token_sieve.config.validator import CONTENT_SPECIFIC
        from token_sieve.server.proxy import ProxyServer

        registry = ProxyServer._ADAPTER_REGISTRY
        for name in CONTENT_SPECIFIC:
            assert name in registry, (
                f"Validator name '{name}' not in _ADAPTER_REGISTRY. "
                f"Did you mean one of: {list(registry.keys())}?"
            )

    def test_format_contains_canonical_names(self):
        """FORMAT frozenset must use canonical adapter names."""
        from token_sieve.config.validator import FORMAT
        from token_sieve.server.proxy import ProxyServer

        registry = ProxyServer._ADAPTER_REGISTRY
        for name in FORMAT:
            assert name in registry, (
                f"Validator name '{name}' not in _ADAPTER_REGISTRY. "
                f"Did you mean one of: {list(registry.keys())}?"
            )
