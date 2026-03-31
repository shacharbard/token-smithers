"""Tests for TokenSieveConfig YAML loading and Pydantic validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from token_sieve.config.schema import (
    BackendConfig,
    CompressionConfig,
    FilterConfig,
    ObservabilityConfig,
    TokenSieveConfig,
    load_config,
)


class TestBackendConfig:
    """BackendConfig nested model."""

    def test_defaults(self) -> None:
        cfg = BackendConfig()
        assert cfg.transport == "stdio"
        assert cfg.command is None
        assert cfg.args == []
        assert cfg.url is None
        assert cfg.env == {}

    def test_custom_values(self) -> None:
        cfg = BackendConfig(
            transport="sse",
            command="uvx",
            args=["mcp-server-filesystem", "/tmp"],
            url="http://localhost:8000",
            env={"API_KEY": "secret"},
        )
        assert cfg.transport == "sse"
        assert cfg.command == "uvx"
        assert cfg.args == ["mcp-server-filesystem", "/tmp"]
        assert cfg.url == "http://localhost:8000"
        assert cfg.env == {"API_KEY": "secret"}


class TestFilterConfig:
    """FilterConfig nested model."""

    def test_defaults(self) -> None:
        cfg = FilterConfig()
        assert cfg.mode == "passthrough"
        assert cfg.tools == []
        assert cfg.patterns == []

    def test_allowlist_mode(self) -> None:
        cfg = FilterConfig(
            mode="allowlist",
            tools=["read_file", "list_dir"],
            patterns=["search_.*"],
        )
        assert cfg.mode == "allowlist"
        assert len(cfg.tools) == 2
        assert len(cfg.patterns) == 1


class TestCompressionConfig:
    """CompressionConfig nested model."""

    def test_defaults(self) -> None:
        cfg = CompressionConfig()
        assert cfg.enabled is True
        assert cfg.strategy == "passthrough"
        assert cfg.max_tokens == 4096
        assert cfg.dedup_window == 50

    def test_custom_values(self) -> None:
        cfg = CompressionConfig(
            enabled=False,
            strategy="truncate",
            max_tokens=8192,
            dedup_window=100,
        )
        assert cfg.enabled is False
        assert cfg.strategy == "truncate"
        assert cfg.max_tokens == 8192
        assert cfg.dedup_window == 100


class TestObservabilityConfig:
    """ObservabilityConfig nested model."""

    def test_defaults(self) -> None:
        cfg = ObservabilityConfig()
        assert cfg.metrics_to_stderr is True
        assert cfg.log_level == "INFO"

    def test_custom_values(self) -> None:
        cfg = ObservabilityConfig(metrics_to_stderr=False, log_level="DEBUG")
        assert cfg.metrics_to_stderr is False
        assert cfg.log_level == "DEBUG"


class TestTokenSieveConfig:
    """Top-level config with nested models."""

    def test_all_defaults(self) -> None:
        cfg = TokenSieveConfig()
        assert isinstance(cfg.backend, BackendConfig)
        assert isinstance(cfg.filter, FilterConfig)
        assert isinstance(cfg.compression, CompressionConfig)
        assert isinstance(cfg.observability, ObservabilityConfig)

    def test_from_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = {
            "backend": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "my_server"],
            },
            "filter": {
                "mode": "allowlist",
                "tools": ["read_file"],
            },
            "compression": {
                "enabled": True,
                "strategy": "truncate",
                "max_tokens": 2048,
            },
            "observability": {
                "log_level": "DEBUG",
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))
        cfg = load_config(config_file)
        assert cfg.backend.command == "python"
        assert cfg.filter.mode == "allowlist"
        assert cfg.compression.max_tokens == 2048
        assert cfg.observability.log_level == "DEBUG"

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        cfg = load_config(missing)
        assert cfg.backend.transport == "stdio"
        assert cfg.filter.mode == "passthrough"

    def test_empty_yaml_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        cfg = load_config(config_file)
        assert isinstance(cfg, TokenSieveConfig)

    def test_partial_yaml_fills_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "partial.yaml"
        config_file.write_text(yaml.dump({"compression": {"max_tokens": 1024}}))
        cfg = load_config(config_file)
        assert cfg.compression.max_tokens == 1024
        assert cfg.compression.strategy == "passthrough"  # default
        assert cfg.backend.transport == "stdio"  # default

    def test_invalid_type_raises_validation_error(self) -> None:
        with pytest.raises(Exception):  # Pydantic ValidationError
            TokenSieveConfig(compression={"max_tokens": "not_a_number"})

    def test_extra_fields_ignored(self, tmp_path: Path) -> None:
        yaml_content = {
            "backend": {"transport": "stdio"},
            "unknown_section": {"key": "value"},
        }
        config_file = tmp_path / "extra.yaml"
        config_file.write_text(yaml.dump(yaml_content))
        cfg = load_config(config_file)
        assert cfg.backend.transport == "stdio"

    def test_yaml_boolean_trap_on_off(self, tmp_path: Path) -> None:
        """YAML 1.1 parses on/off as booleans. Config should handle gracefully."""
        raw_yaml = "compression:\n  enabled: on\nobservability:\n  metrics_to_stderr: off\n"
        config_file = tmp_path / "bool_trap.yaml"
        config_file.write_text(raw_yaml)
        cfg = load_config(config_file)
        # YAML 1.1 (PyYAML) parses 'on' as True, 'off' as False
        assert cfg.compression.enabled is True
        assert cfg.observability.metrics_to_stderr is False

    def test_yaml_boolean_trap_yes_no(self, tmp_path: Path) -> None:
        """YAML 1.1 parses yes/no as booleans."""
        raw_yaml = "compression:\n  enabled: yes\nobservability:\n  metrics_to_stderr: no\n"
        config_file = tmp_path / "bool_trap2.yaml"
        config_file.write_text(raw_yaml)
        cfg = load_config(config_file)
        assert cfg.compression.enabled is True
        assert cfg.observability.metrics_to_stderr is False

    def test_negative_max_tokens_raises(self) -> None:
        with pytest.raises(Exception):
            TokenSieveConfig(compression={"max_tokens": -1})

    def test_negative_dedup_window_raises(self) -> None:
        with pytest.raises(Exception):
            TokenSieveConfig(compression={"dedup_window": -1})
