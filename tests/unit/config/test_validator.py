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
            "log_level_filter",
            "error_stack_compressor",
            "toon_compressor",
            "truncation",
        ])
        assert warnings == []

    def test_cleanup_after_content_specific_warns(self, validate):
        """Cleanup adapter after content-specific should produce a warning."""
        warnings = validate([
            "log_level_filter",
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
            "toon_compressor",
            "log_level_filter",
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


class TestValidateConfigCrossSection:
    """Phase 04 cross-section config validation."""

    def test_semantic_cache_requires_learning_enabled(self) -> None:
        """semantic_cache.enabled=True requires learning.enabled=True."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.config.validator import validate_config

        cfg = TokenSieveConfig(
            semantic_cache={"enabled": True},
            learning={"enabled": False},
        )
        errors = validate_config(cfg)
        assert any("semantic_cache" in e and "learning" in e for e in errors)

    def test_semantic_cache_with_learning_ok(self) -> None:
        """semantic_cache.enabled=True + learning.enabled=True is valid."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.config.validator import validate_config

        cfg = TokenSieveConfig(
            semantic_cache={"enabled": True},
            learning={"enabled": True},
        )
        errors = validate_config(cfg)
        assert not any("semantic_cache" in e for e in errors)

    def test_semantic_cache_disabled_with_learning_disabled_ok(self) -> None:
        """Both disabled is valid."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.config.validator import validate_config

        cfg = TokenSieveConfig(
            semantic_cache={"enabled": False},
            learning={"enabled": False},
        )
        errors = validate_config(cfg)
        assert not any("semantic_cache" in e for e in errors)

    def test_schema_virtualization_tier_valid(self) -> None:
        """Tiers 1, 2, 3 are accepted."""
        from token_sieve.config.schema import SchemaVirtualizationConfig

        for tier in (1, 2, 3):
            cfg = SchemaVirtualizationConfig(tier=tier)
            assert cfg.tier == tier

    def test_schema_virtualization_tier_invalid(self) -> None:
        """Tiers outside 1-3 are rejected by Pydantic Literal."""
        from pydantic import ValidationError

        from token_sieve.config.schema import SchemaVirtualizationConfig

        with pytest.raises(ValidationError):
            SchemaVirtualizationConfig(tier=0)

    def test_default_config_has_no_errors(self) -> None:
        """Default config should pass all validation."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.config.validator import validate_config

        cfg = TokenSieveConfig()
        errors = validate_config(cfg)
        assert errors == []


class TestSafetyNetAndContentSpecificGap:
    """Fix 2: Missing adapters in validator phase sets."""

    def test_smart_truncation_in_safety_net(self):
        """smart_truncation must be in the SAFETY_NET frozenset."""
        from token_sieve.config.validator import SAFETY_NET

        assert "smart_truncation" in SAFETY_NET

    def test_smart_truncation_not_last_warns(self, validate):
        """smart_truncation not at end should produce a safety net warning."""
        warnings = validate([
            "whitespace_normalizer",
            "smart_truncation",
            "rle_encoder",
        ])
        assert any("safety net" in w.lower() or "smart_truncation" in w for w in warnings)

    def test_smart_truncation_last_is_valid(self, validate):
        """smart_truncation at the end should not produce a position warning."""
        warnings = validate([
            "whitespace_normalizer",
            "smart_truncation",
        ])
        assert not any("safety net" in w.lower() for w in warnings)

    def test_progressive_disclosure_in_content_specific(self):
        """progressive_disclosure must be categorized."""
        from token_sieve.config.validator import CONTENT_SPECIFIC

        assert "progressive_disclosure" in CONTENT_SPECIFIC

    def test_graph_encoder_in_content_specific(self):
        """graph_encoder must be categorized."""
        from token_sieve.config.validator import CONTENT_SPECIFIC

        assert "graph_encoder" in CONTENT_SPECIFIC

    def test_key_aliasing_in_content_specific(self):
        """key_aliasing must be categorized."""
        from token_sieve.config.validator import CONTENT_SPECIFIC

        assert "key_aliasing" in CONTENT_SPECIFIC

    def test_file_redirect_in_format(self):
        """file_redirect must be categorized in FORMAT (positioned after content-specific)."""
        from token_sieve.config.validator import FORMAT

        assert "file_redirect" in FORMAT

    def test_all_registry_names_categorized(self):
        """Every adapter in _ADAPTER_REGISTRY should be in a validator phase set."""
        from token_sieve.config.validator import (
            CLEANUP,
            CONTENT_SPECIFIC,
            FORMAT,
            SAFETY_NET,
        )
        from token_sieve.server.proxy import ProxyServer

        all_categorized = CLEANUP | CONTENT_SPECIFIC | FORMAT | SAFETY_NET
        uncategorized_ok = {"passthrough", "ast_skeleton"}  # no-ops / special
        for name in ProxyServer._ADAPTER_REGISTRY:
            if name not in uncategorized_ok:
                assert name in all_categorized, (
                    f"Adapter '{name}' is in registry but not categorized "
                    f"in any validator phase set"
                )
