"""Configuration schema for token-sieve.

Uses pure yaml.safe_load + nested Pydantic BaseModel (no pydantic-settings).
Config file not found returns defaults gracefully.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class BackendConfig(BaseModel):
    """Backend MCP server connection settings."""

    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class FilterConfig(BaseModel):
    """Tool filtering configuration."""

    mode: Literal["passthrough", "allowlist", "blocklist"] = "passthrough"
    tools: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class AdapterConfig(BaseModel):
    """Per-adapter configuration entry.

    Each entry in the ordered adapter list specifies the adapter name,
    whether it's enabled, and any adapter-specific settings.
    """

    name: str
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


def _default_adapters() -> list[AdapterConfig]:
    """Default adapter ordering per Decision 5.

    Cleanup -> Content-specific lossy -> Sentence/RLE ->
    Format transforms -> FileRedirect -> SmartTruncation (safety net).
    """
    return [
        # Cleanup layer
        AdapterConfig(name="whitespace_normalizer"),
        AdapterConfig(name="null_field_elider"),
        AdapterConfig(name="path_prefix_deduplicator"),
        AdapterConfig(name="timestamp_normalizer"),
        # Content-specific lossy (off by default)
        AdapterConfig(name="log_level_filter", enabled=False),
        AdapterConfig(name="error_stack_compressor", enabled=False),
        AdapterConfig(name="code_comment_stripper", enabled=False),
        # Sentence scorer + RLE
        AdapterConfig(name="sentence_scorer", enabled=False),
        AdapterConfig(name="rle_encoder"),
        # Format transforms (mutually exclusive via transformed_by)
        AdapterConfig(name="toon_compressor"),
        AdapterConfig(name="yaml_transcoder"),
        # File redirect
        AdapterConfig(name="file_redirect", enabled=False),
        # Safety net (always last)
        AdapterConfig(name="smart_truncation"),
    ]


class CompressionConfig(BaseModel):
    """Compression pipeline settings."""

    model_config = {"extra": "forbid"}

    enabled: bool = True
    strategy: str = "passthrough"
    max_tokens: int = 4096
    dedup_window: int = 50
    size_gate_threshold: int = 2000
    adapters: list[AdapterConfig] = Field(default_factory=_default_adapters)

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_tokens must be non-negative")
        return v

    @field_validator("dedup_window")
    @classmethod
    def dedup_window_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("dedup_window must be non-negative")
        return v


class ObservabilityConfig(BaseModel):
    """Observability / logging settings."""

    metrics_to_stderr: bool = True
    log_level: str = "INFO"


class TokenSieveConfig(BaseModel):
    """Top-level token-sieve configuration.

    Validates YAML input via Pydantic BaseModel with nested config sections.
    Extra top-level fields are silently ignored (forward-compat).
    """

    model_config = {"extra": "ignore"}

    backend: BackendConfig = Field(default_factory=BackendConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


def load_config(path: Path) -> TokenSieveConfig:
    """Load config from YAML file. Missing file returns defaults."""
    if not path.exists():
        return TokenSieveConfig()
    raw = path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(raw) or {}
    return TokenSieveConfig(**data)
