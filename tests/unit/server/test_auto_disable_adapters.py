"""Tests for auto-disabling adapters for self-compressing backends.

When the proxy wraps a backend that already optimizes its output
(jCodeMunch, jDocMunch, context-mode), TreeSitterASTExtractor should
be auto-disabled to avoid destructive double-compression.
"""
from __future__ import annotations

import pytest

from token_sieve.config.schema import TokenSieveConfig
from token_sieve.domain.model import ContentType
from token_sieve.server.proxy import ProxyServer


def _get_strategy_names(proxy: ProxyServer) -> list[str]:
    """Extract strategy class names from the proxy's pipeline."""
    strategies = proxy._pipeline._routes.get(ContentType.TEXT, [])
    return [type(s).__name__ for s in strategies]


class TestAutoDisableTreeSitterForSelfCompressingBackends:
    """TreeSitterASTExtractor auto-disabled for known self-compressing backends."""

    @pytest.mark.parametrize(
        "command",
        ["jcodemunch-mcp", "jdocmunch-mcp", "context-mode"],
    )
    def test_tree_sitter_disabled_for_self_compressing_backend(
        self, command: str
    ) -> None:
        """Proxy auto-disables TreeSitterASTExtractor when backend is self-compressing."""
        config = TokenSieveConfig(
            backend={"command": command, "args": ["serve"]},
        )

        proxy = ProxyServer.create_from_config(config)
        names = _get_strategy_names(proxy)

        assert "TreeSitterASTExtractor" not in names

    def test_tree_sitter_enabled_for_non_self_compressing_backend(self) -> None:
        """Proxy keeps TreeSitterASTExtractor for backends that don't self-compress."""
        config = TokenSieveConfig(
            backend={"command": "muninndb-lite", "args": ["mcp"]},
        )

        proxy = ProxyServer.create_from_config(config)
        names = _get_strategy_names(proxy)

        assert "TreeSitterASTExtractor" in names

    def test_tree_sitter_enabled_when_no_backend_command(self) -> None:
        """Default (no backend command) keeps TreeSitterASTExtractor enabled."""
        config = TokenSieveConfig()

        proxy = ProxyServer.create_from_config(config)
        names = _get_strategy_names(proxy)

        assert "TreeSitterASTExtractor" in names

    @pytest.mark.parametrize(
        "command",
        ["jcodemunch-mcp", "jdocmunch-mcp", "context-mode"],
    )
    def test_other_adapters_still_registered(self, command: str) -> None:
        """Non-TreeSitter adapters remain active for self-compressing backends."""
        config = TokenSieveConfig(
            backend={"command": command, "args": []},
        )

        proxy = ProxyServer.create_from_config(config)
        names = _get_strategy_names(proxy)

        # These lightweight adapters should still be present
        assert "WhitespaceNormalizer" in names
        assert "NullFieldElider" in names
