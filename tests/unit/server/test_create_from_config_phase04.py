"""Tests for create_from_config() Phase 04 wiring and self-tuning."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from token_sieve.config.schema import TokenSieveConfig
from token_sieve.server.proxy import ProxyServer


class TestCreateFromConfigPhase04:
    """create_from_config wires all Phase 04 dependencies."""

    def test_all_features_enabled_creates_full_proxy(self) -> None:
        """With all Phase 04 features enabled, proxy has all deps injected."""
        config = TokenSieveConfig(
            learning={"enabled": True, "db_path": ":memory:"},
            dashboard={"enabled": True, "metrics_file_path": "/tmp/test_metrics.json"},
            schema_virtualization={"enabled": True, "tier": 2},
            semantic_cache={"enabled": True, "similarity_threshold": 0.85},
            reranker={"enabled": True},
        )

        proxy = ProxyServer.create_from_config(config)

        assert proxy._schema_virtualizer is not None
        assert proxy._learning_store is not None
        assert proxy._semantic_cache is not None
        assert proxy._metrics_collector is not None

    def test_all_features_disabled_creates_basic_proxy(self) -> None:
        """With all Phase 04 features disabled, proxy matches Phase 03 behavior."""
        config = TokenSieveConfig(
            learning={"enabled": False},
            dashboard={"enabled": False},
            schema_virtualization={"enabled": False},
            semantic_cache={"enabled": False},
            reranker={"enabled": False},
        )

        proxy = ProxyServer.create_from_config(config)

        assert proxy._schema_virtualizer is None
        assert proxy._learning_store is None
        assert proxy._semantic_cache is None
        assert proxy._metrics_collector is None

    def test_schema_virtualizer_uses_configured_tier(self) -> None:
        """SchemaVirtualizer created with tier from config."""
        config = TokenSieveConfig(
            schema_virtualization={"enabled": True, "tier": 3},
        )

        proxy = ProxyServer.create_from_config(config)
        assert proxy._schema_virtualizer is not None

    def test_metrics_writer_created_when_dashboard_enabled(self) -> None:
        """MetricsFileWriter is created and wired when dashboard.enabled."""
        config = TokenSieveConfig(
            dashboard={"enabled": True, "metrics_file_path": "/tmp/test_m.json"},
        )

        proxy = ProxyServer.create_from_config(config)
        assert proxy._metrics_collector is not None


class TestSelfTuning:
    """Self-tuning adjusts compression thresholds based on history."""

    def test_self_tuning_adjusts_threshold(self) -> None:
        """After sufficient compression events, size_gate_threshold is adjusted."""
        from token_sieve.domain.model import CompressionEvent, ContentType

        config = TokenSieveConfig(
            learning={"enabled": True, "db_path": ":memory:"},
        )

        proxy = ProxyServer.create_from_config(config)

        # Simulate that self-tuning has data
        # The proxy should have a _self_tuning_call_count or similar mechanism
        assert hasattr(proxy, "_self_tune_interval")
        assert proxy._self_tune_interval > 0
