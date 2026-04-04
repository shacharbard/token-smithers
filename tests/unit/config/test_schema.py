"""Tests for TokenSieveConfig YAML loading and Pydantic validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from token_sieve.config.schema import (
    AdapterConfig,
    AttentionConfig,
    BackendConfig,
    CacheConfig,
    CompressionConfig,
    FilterConfig,
    ObservabilityConfig,
    RerankerConfig,
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


class TestFilterConfigModeValidation:
    """FilterConfig.mode must reject invalid mode strings at construction."""

    def test_invalid_mode_rejected(self) -> None:
        """Typos like 'allow-list' must raise ValidationError, not silently pass."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FilterConfig(mode="allow-list")

    def test_garbage_mode_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FilterConfig(mode="foobar")


class TestAdapterConfig:
    """AdapterConfig model for per-adapter settings."""

    def test_defaults(self) -> None:
        cfg = AdapterConfig(name="whitespace_normalizer")
        assert cfg.name == "whitespace_normalizer"
        assert cfg.enabled is True
        assert cfg.settings == {}

    def test_custom_settings(self) -> None:
        cfg = AdapterConfig(
            name="log_filter",
            enabled=True,
            settings={"retain_levels": ["ERROR", "WARN"]},
        )
        assert cfg.name == "log_filter"
        assert cfg.settings["retain_levels"] == ["ERROR", "WARN"]

    def test_disabled_adapter(self) -> None:
        cfg = AdapterConfig(name="sentence_scorer", enabled=False)
        assert cfg.enabled is False


class TestCompressionConfigAdapters:
    """CompressionConfig extended with ordered adapter list."""

    def test_default_adapters_list(self) -> None:
        """Default adapter list follows Decision 5 ordering."""
        cfg = CompressionConfig()
        assert isinstance(cfg.adapters, list)
        assert len(cfg.adapters) > 0
        # All entries are AdapterConfig
        for adapter in cfg.adapters:
            assert isinstance(adapter, AdapterConfig)

    def test_default_adapter_ordering(self) -> None:
        """Default ordering: cleanup first, then lossy, then transforms, then safety nets."""
        cfg = CompressionConfig()
        names = [a.name for a in cfg.adapters]
        # Cleanup adapters should come before format transforms
        assert names.index("whitespace_normalizer") < names.index("toon_compressor")
        # Safety nets should come last
        assert names.index("smart_truncation") == len(names) - 1

    def test_custom_adapter_order(self) -> None:
        """Custom adapter order is accepted."""
        custom = [
            AdapterConfig(name="whitespace_normalizer"),
            AdapterConfig(name="smart_truncation"),
        ]
        cfg = CompressionConfig(adapters=custom)
        assert len(cfg.adapters) == 2
        assert cfg.adapters[0].name == "whitespace_normalizer"

    def test_per_adapter_settings(self) -> None:
        """Per-adapter settings are passed through."""
        custom = [
            AdapterConfig(
                name="sentence_scorer",
                settings={"sentence_count": 3},
            ),
        ]
        cfg = CompressionConfig(adapters=custom)
        assert cfg.adapters[0].settings["sentence_count"] == 3

    def test_size_gate_threshold_field(self) -> None:
        """CompressionConfig has a size_gate_threshold field defaulting to 500."""
        cfg = CompressionConfig()
        assert cfg.size_gate_threshold == 500

    def test_custom_size_gate_threshold(self) -> None:
        cfg = CompressionConfig(size_gate_threshold=5000)
        assert cfg.size_gate_threshold == 5000

    def test_phase06_adapters_enabled_by_default(self) -> None:
        """json_code_unwrapper and tree_sitter_ast should be enabled by default."""
        cfg = CompressionConfig()
        adapter_map = {a.name: a for a in cfg.adapters}
        assert adapter_map["json_code_unwrapper"].enabled is True
        assert adapter_map["tree_sitter_ast"].enabled is True

    def test_backward_compatibility_no_adapters(self) -> None:
        """Config without adapters key uses default adapter list."""
        cfg = CompressionConfig(enabled=True, strategy="passthrough")
        assert len(cfg.adapters) > 0  # defaults populated


class TestRerankerConfig:
    """RerankerConfig for statistical reranker settings."""

    def test_defaults(self) -> None:
        cfg = RerankerConfig()
        assert cfg.enabled is True
        assert cfg.max_tools == 500
        assert cfg.recency_weight == 0.3

    def test_custom_values(self) -> None:
        cfg = RerankerConfig(enabled=False, max_tools=100, recency_weight=0.5)
        assert cfg.enabled is False
        assert cfg.max_tools == 100
        assert cfg.recency_weight == 0.5


class TestCacheConfig:
    """CacheConfig for schema cache and call cache settings."""

    def test_defaults(self) -> None:
        cfg = CacheConfig()
        assert cfg.schema_cache_ttl == 3600.0
        assert cfg.call_cache_max == 200
        assert cfg.diff_store_max == 100

    def test_custom_values(self) -> None:
        cfg = CacheConfig(schema_cache_ttl=60.0, call_cache_max=50, diff_store_max=25)
        assert cfg.schema_cache_ttl == 60.0
        assert cfg.call_cache_max == 50
        assert cfg.diff_store_max == 25


class TestTokenSieveConfigExtended:
    """TokenSieveConfig with reranker and cache sections."""

    def test_reranker_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        assert isinstance(cfg.reranker, RerankerConfig)
        assert cfg.reranker.enabled is True

    def test_cache_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        assert isinstance(cfg.cache, CacheConfig)
        assert cfg.cache.schema_cache_ttl == 3600.0

    def test_backward_compatible_without_new_sections(self) -> None:
        """Old configs without reranker/cache/attention sections still work."""
        cfg = TokenSieveConfig(backend={"transport": "stdio"})
        assert isinstance(cfg.reranker, RerankerConfig)
        assert isinstance(cfg.cache, CacheConfig)
        assert isinstance(cfg.attention, AttentionConfig)


class TestAttentionConfig:
    """AttentionConfig for attention tracking settings."""

    def test_defaults(self) -> None:
        cfg = AttentionConfig()
        assert cfg.enabled is False
        assert cfg.max_tools == 500

    def test_custom_values(self) -> None:
        cfg = AttentionConfig(enabled=True, max_tools=100)
        assert cfg.enabled is True
        assert cfg.max_tools == 100

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AttentionConfig(unknown_field="bad")

    def test_attention_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        assert isinstance(cfg.attention, AttentionConfig)
        assert cfg.attention.enabled is False
        assert cfg.attention.max_tools == 500

    def test_attention_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = {"attention": {"enabled": True, "max_tools": 200}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))
        cfg = load_config(config_file)
        assert cfg.attention.enabled is True
        assert cfg.attention.max_tools == 200


class TestLearningConfig:
    """LearningConfig for cross-session persistence settings."""

    def test_defaults(self) -> None:
        from token_sieve.config.schema import LearningConfig

        cfg = LearningConfig()
        assert cfg.enabled is True
        assert cfg.db_path == "~/.token-sieve/learning.db"

    def test_custom_values(self) -> None:
        from token_sieve.config.schema import LearningConfig

        cfg = LearningConfig(enabled=False, db_path="/tmp/test.db")
        assert cfg.enabled is False
        assert cfg.db_path == "/tmp/test.db"

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from token_sieve.config.schema import LearningConfig

        with pytest.raises(ValidationError):
            LearningConfig(unknown_field="bad")

    def test_learning_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        from token_sieve.config.schema import LearningConfig

        assert isinstance(cfg.learning, LearningConfig)
        assert cfg.learning.enabled is True


class TestDashboardConfig:
    """DashboardConfig for metrics dashboard settings."""

    def test_defaults(self) -> None:
        from token_sieve.config.schema import DashboardConfig

        cfg = DashboardConfig()
        assert cfg.enabled is True
        assert cfg.metrics_file_path == "~/.token-sieve/metrics.json"

    def test_custom_values(self) -> None:
        from token_sieve.config.schema import DashboardConfig

        cfg = DashboardConfig(enabled=False, metrics_file_path="/tmp/metrics.json")
        assert cfg.enabled is False
        assert cfg.metrics_file_path == "/tmp/metrics.json"

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from token_sieve.config.schema import DashboardConfig

        with pytest.raises(ValidationError):
            DashboardConfig(unknown_field="bad")

    def test_dashboard_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        from token_sieve.config.schema import DashboardConfig

        assert isinstance(cfg.dashboard, DashboardConfig)
        assert cfg.dashboard.enabled is True


class TestSchemaVirtualizationConfig:
    """SchemaVirtualizationConfig for DietMCP-style elision."""

    def test_defaults(self) -> None:
        from token_sieve.config.schema import SchemaVirtualizationConfig

        cfg = SchemaVirtualizationConfig()
        assert cfg.enabled is True
        assert cfg.tier == 2
        assert cfg.frequent_call_threshold == 3

    def test_custom_values(self) -> None:
        from token_sieve.config.schema import SchemaVirtualizationConfig

        cfg = SchemaVirtualizationConfig(enabled=True, tier=3, frequent_call_threshold=5)
        assert cfg.enabled is True
        assert cfg.tier == 3
        assert cfg.frequent_call_threshold == 5

    def test_tier_literal_values(self) -> None:
        """Tier must be 1, 2, or 3."""
        from pydantic import ValidationError

        from token_sieve.config.schema import SchemaVirtualizationConfig

        with pytest.raises(ValidationError):
            SchemaVirtualizationConfig(tier=4)

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from token_sieve.config.schema import SchemaVirtualizationConfig

        with pytest.raises(ValidationError):
            SchemaVirtualizationConfig(unknown_field="bad")

    def test_schema_virt_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        from token_sieve.config.schema import SchemaVirtualizationConfig

        assert isinstance(cfg.schema_virtualization, SchemaVirtualizationConfig)
        assert cfg.schema_virtualization.enabled is True


class TestSystemPromptConfig:
    """SystemPromptConfig for system prompt optimization."""

    def test_defaults(self) -> None:
        from token_sieve.config.schema import SystemPromptConfig

        cfg = SystemPromptConfig()
        assert cfg.enabled is True
        assert cfg.compress_instructions is True

    def test_custom_values(self) -> None:
        from token_sieve.config.schema import SystemPromptConfig

        cfg = SystemPromptConfig(enabled=False, compress_instructions=False)
        assert cfg.enabled is False
        assert cfg.compress_instructions is False

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from token_sieve.config.schema import SystemPromptConfig

        with pytest.raises(ValidationError):
            SystemPromptConfig(unknown_field="bad")

    def test_system_prompt_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        from token_sieve.config.schema import SystemPromptConfig

        assert isinstance(cfg.system_prompt, SystemPromptConfig)
        assert cfg.system_prompt.enabled is True


class TestSemanticCacheConfig:
    """SemanticCacheConfig for semantic result caching."""

    def test_defaults(self) -> None:
        from token_sieve.config.schema import SemanticCacheConfig

        cfg = SemanticCacheConfig()
        assert cfg.enabled is False
        assert cfg.similarity_threshold == 0.85
        assert cfg.max_entries == 1000
        assert cfg.ttl_seconds is None

    def test_custom_values(self) -> None:
        from token_sieve.config.schema import SemanticCacheConfig

        cfg = SemanticCacheConfig(
            enabled=True, similarity_threshold=0.9, max_entries=500, ttl_seconds=3600
        )
        assert cfg.enabled is True
        assert cfg.similarity_threshold == 0.9
        assert cfg.max_entries == 500
        assert cfg.ttl_seconds == 3600

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        from token_sieve.config.schema import SemanticCacheConfig

        with pytest.raises(ValidationError):
            SemanticCacheConfig(unknown_field="bad")

    def test_semantic_cache_defaults_in_config(self) -> None:
        cfg = TokenSieveConfig()
        from token_sieve.config.schema import SemanticCacheConfig

        assert isinstance(cfg.semantic_cache, SemanticCacheConfig)
        assert cfg.semantic_cache.enabled is False


class TestPhase04ConfigYamlRoundTrip:
    """Phase 04 config sections survive YAML round-trip."""

    def test_yaml_round_trip_preserves_new_fields(self, tmp_path: Path) -> None:
        yaml_content = {
            "learning": {"enabled": True, "db_path": "/custom/path.db"},
            "dashboard": {"enabled": False, "metrics_file_path": "/tmp/m.json"},
            "schema_virtualization": {"enabled": True, "tier": 3, "frequent_call_threshold": 5},
            "system_prompt": {"enabled": False, "compress_instructions": False},
            "semantic_cache": {"enabled": True, "similarity_threshold": 0.9, "max_entries": 500, "ttl_seconds": 7200},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))
        cfg = load_config(config_file)
        assert cfg.learning.db_path == "/custom/path.db"
        assert cfg.dashboard.enabled is False
        assert cfg.schema_virtualization.tier == 3
        assert cfg.system_prompt.compress_instructions is False
        assert cfg.semantic_cache.ttl_seconds == 7200

    def test_backward_compatible_without_phase04_sections(self) -> None:
        """Old configs without Phase 04 sections still work."""
        cfg = TokenSieveConfig(backend={"transport": "stdio"})
        assert cfg.learning.enabled is True
        assert cfg.dashboard.enabled is True
        assert cfg.schema_virtualization.enabled is True
        assert cfg.system_prompt.enabled is True
        assert cfg.semantic_cache.enabled is False
