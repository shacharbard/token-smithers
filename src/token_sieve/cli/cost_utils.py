"""Cost estimation utilities using tokencost (optional dependency).

Provides helpers for displaying dollar savings in the stats and estimate
CLI commands. All functions gracefully degrade when tokencost is not installed.
"""
from __future__ import annotations

import os
from typing import Any

# Default model for cost estimation
_DEFAULT_MODEL = "claude-sonnet-4-5"


def _get_tokencost() -> Any:
    """Try to import tokencost. Returns module or None."""
    try:
        import tokencost

        return tokencost
    except (ImportError, ModuleNotFoundError):
        return None


def get_model(config_model: str | None = None) -> str:
    """Resolve model name from env var, config, or default.

    Priority: TOKEN_SIEVE_MODEL env var > config_model > default.
    """
    env_model = os.environ.get("TOKEN_SIEVE_MODEL")
    if env_model:
        return env_model
    if config_model:
        return config_model
    return _DEFAULT_MODEL


def estimate_cost(
    original_tokens: int,
    compressed_tokens: int,
    model: str,
) -> dict[str, float] | None:
    """Estimate cost savings from compression.

    Returns dict with 'original_cost', 'compressed_cost', 'saved' keys
    (all in USD), or None if tokencost is not available.
    """
    tc = _get_tokencost()
    if tc is None:
        return None

    try:
        # tokencost provides per-token pricing
        # Use output token pricing since these are tool results (output from MCP)
        original_cost = tc.calculate_cost_by_tokens(original_tokens, 0, model)
        compressed_cost = tc.calculate_cost_by_tokens(compressed_tokens, 0, model)
        saved = float(original_cost - compressed_cost)
        return {
            "original_cost": float(original_cost),
            "compressed_cost": float(compressed_cost),
            "saved": saved,
        }
    except Exception:
        return None


def estimate_session_cost(
    tokens_saved: int,
    model: str,
    sessions_per_day: int = 5,
) -> dict[str, float] | None:
    """Estimate daily cost savings for the estimate command.

    Returns dict with 'cost_per_day_saved' or None if tokencost unavailable.
    """
    tc = _get_tokencost()
    if tc is None:
        return None

    try:
        cost_per_session = tc.calculate_cost_by_tokens(tokens_saved, 0, model)
        cost_per_day = float(cost_per_session) * sessions_per_day
        return {
            "cost_per_day_saved": cost_per_day,
        }
    except Exception:
        return None


def format_cost(amount: float) -> str:
    """Format a dollar amount: 0.0034 -> '$0.003', 1.5 -> '$1.50'."""
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"
