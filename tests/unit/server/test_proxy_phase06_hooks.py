"""Tests for Phase 06 proxy hooks: tree-sitter AST + JSON code unwrapper registration.

Verifies:
- tree_sitter_ast and json_code_unwrapper exist in _ADAPTER_REGISTRY
- ast_skeleton alias still resolves (backward compat) with deprecation warning
- Default adapter ordering includes both new adapters
- json_code_unwrapper comes BEFORE tree_sitter_ast in defaults
"""
from __future__ import annotations

import warnings

import pytest

from token_sieve.server.proxy import ProxyServer


class TestAdapterRegistryPhase06:
    """Phase 06 adapters are in the adapter registry."""

    def test_tree_sitter_ast_in_registry(self) -> None:
        assert "tree_sitter_ast" in ProxyServer._ADAPTER_REGISTRY

    def test_json_code_unwrapper_in_registry(self) -> None:
        assert "json_code_unwrapper" in ProxyServer._ADAPTER_REGISTRY

    def test_ast_skeleton_alias_still_in_registry(self) -> None:
        """Backward-compat: ast_skeleton key must still exist."""
        assert "ast_skeleton" in ProxyServer._ADAPTER_REGISTRY

    def test_ast_skeleton_maps_to_tree_sitter_extractor(self) -> None:
        """ast_skeleton alias must now point to TreeSitterASTExtractor."""
        _module, class_name = ProxyServer._ADAPTER_REGISTRY["ast_skeleton"]
        assert class_name == "TreeSitterASTExtractor"

    def test_ast_skeleton_deprecation_warning(self) -> None:
        """Using ast_skeleton name should emit a DeprecationWarning."""
        from token_sieve.config.schema import AdapterConfig, TokenSieveConfig

        config = TokenSieveConfig(
            compression={
                "adapters": [
                    {"name": "ast_skeleton"},
                ],
            }
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ProxyServer.create_from_config(config)

        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1, (
            f"Expected DeprecationWarning for 'ast_skeleton', got: {w}"
        )
        assert "ast_skeleton" in str(deprecation_warnings[0].message)


class TestDefaultAdapterOrderPhase06:
    """Default adapter ordering includes Phase 06 adapters correctly."""

    def test_json_code_unwrapper_in_defaults(self) -> None:
        """json_code_unwrapper must appear in _default_adapters()."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        assert "json_code_unwrapper" in names

    def test_tree_sitter_ast_in_defaults(self) -> None:
        """tree_sitter_ast must appear in _default_adapters()."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        assert "tree_sitter_ast" in names

    def test_unwrapper_before_ast_in_defaults(self) -> None:
        """json_code_unwrapper MUST come before tree_sitter_ast."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        unwrapper_idx = names.index("json_code_unwrapper")
        ast_idx = names.index("tree_sitter_ast")
        assert unwrapper_idx < ast_idx, (
            f"json_code_unwrapper (idx={unwrapper_idx}) must come before "
            f"tree_sitter_ast (idx={ast_idx})"
        )

    def test_both_disabled_by_default(self) -> None:
        """Both Phase 06 adapters should be disabled by default."""
        from token_sieve.config.schema import _default_adapters

        adapters = {a.name: a for a in _default_adapters()}
        assert adapters["json_code_unwrapper"].enabled is False
        assert adapters["tree_sitter_ast"].enabled is False
