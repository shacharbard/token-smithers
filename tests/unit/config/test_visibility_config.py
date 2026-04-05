"""Tests for ToolVisibilityConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from token_sieve.config.schema import TokenSieveConfig, ToolVisibilityConfig


class TestToolVisibilityConfig:
    """ToolVisibilityConfig defaults and validation."""

    def test_defaults(self) -> None:
        """All default values match the spec."""
        cfg = ToolVisibilityConfig()
        assert cfg.enabled is True
        assert cfg.frequency_threshold == 3
        assert cfg.min_visible_floor == 10
        assert cfg.cold_start_sessions == 3
        assert cfg.discover_tools_threshold == 5

    def test_extra_forbid(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(ValidationError):
            ToolVisibilityConfig(bogus_field=42)

    def test_custom_values(self) -> None:
        """Custom values are accepted."""
        cfg = ToolVisibilityConfig(
            enabled=False,
            frequency_threshold=5,
            min_visible_floor=20,
            cold_start_sessions=5,
            discover_tools_threshold=10,
        )
        assert cfg.enabled is False
        assert cfg.frequency_threshold == 5
        assert cfg.min_visible_floor == 20
        assert cfg.cold_start_sessions == 5
        assert cfg.discover_tools_threshold == 10


class TestTokenSieveConfigToolVisibility:
    """TokenSieveConfig has tool_visibility field."""

    def test_token_sieve_config_has_tool_visibility(self) -> None:
        """TokenSieveConfig includes tool_visibility with correct type."""
        cfg = TokenSieveConfig()
        assert isinstance(cfg.tool_visibility, ToolVisibilityConfig)

    def test_tool_visibility_defaults_in_config(self) -> None:
        """tool_visibility defaults propagate through TokenSieveConfig."""
        cfg = TokenSieveConfig()
        assert cfg.tool_visibility.enabled is True
        assert cfg.tool_visibility.frequency_threshold == 3
