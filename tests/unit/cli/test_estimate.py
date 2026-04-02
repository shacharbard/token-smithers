"""Tests for token-smithers estimate command."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from token_sieve.cli.estimate import (
    DEFAULT_PROFILE,
    ServerProfile,
    estimate_session_savings,
    match_profile,
    run_estimate,
)
from token_sieve.cli.main import main
from token_sieve.cli.setup import McpConfigFile, McpServerEntry


class TestMatchProfile:
    """match_profile resolves known servers, skips optimized, returns None for unknown."""

    def test_match_profile_known_server(self) -> None:
        """'context7' in server name matches context7 profile."""
        profile = match_profile(server_name="context7", command="npx")
        assert profile is not None
        assert profile.name == "context7"
        assert profile.schema_saved_pct == 64
        assert profile.category == "docs"

    def test_match_profile_by_command(self) -> None:
        """Command containing 'filesystem' matches Filesystem profile."""
        profile = match_profile(server_name="my-fs-server", command="server-filesystem")
        assert profile is not None
        assert profile.name == "Filesystem"
        assert profile.tools == 8
        assert profile.schema_saved_pct == 41

    def test_match_profile_skip_optimized(self) -> None:
        """Already-optimized servers like 'jcodemunch' return None."""
        profile = match_profile(server_name="jcodemunch", command="npx")
        assert profile is None

    def test_match_profile_unknown(self) -> None:
        """Unknown server with no matching key returns None."""
        profile = match_profile(
            server_name="some-random-server", command="some-random-cmd"
        )
        assert profile is None


class TestEstimateSessionSavings:
    """estimate_session_savings calculates token savings correctly."""

    def test_estimate_session_savings(self) -> None:
        """Verify math: schema savings from refreshes + result savings from calls."""
        profiles = [
            ServerProfile(
                name="TestA",
                tools=10,
                schema_saved_pct=50,
                result_saved_pct=40,
                category="api",
            ),
            ServerProfile(
                name="TestB",
                tools=5,
                schema_saved_pct=30,
                result_saved_pct=60,
                category="search",
            ),
        ]
        result = estimate_session_savings(
            profiles, calls_per_session=10, refreshes=5
        )
        assert "schema_tokens_saved" in result
        assert "result_tokens_saved" in result
        assert "total_tokens_saved" in result
        assert result["total_tokens_saved"] == (
            result["schema_tokens_saved"] + result["result_tokens_saved"]
        )
        # Values should be positive
        assert result["schema_tokens_saved"] > 0
        assert result["result_tokens_saved"] > 0


class TestRunEstimate:
    """run_estimate discovers servers, matches profiles, prints table."""

    def test_run_estimate_no_configs(self, capsys: pytest.CaptureFixture) -> None:
        """No configs found prints a message and returns 0."""
        with patch(
            "token_sieve.cli.estimate.discover_mcp_configs", return_value=[]
        ):
            code = run_estimate()

        assert code == 0
        captured = capsys.readouterr()
        assert "no mcp" in captured.out.lower() or "no servers" in captured.out.lower()


class TestMainRoutesEstimate:
    """main() routes 'estimate' subcommand to run_estimate."""

    def test_main_routes_estimate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main(["estimate"]) dispatches to run_estimate."""
        called = False

        def fake_run_estimate() -> int:
            nonlocal called
            called = True
            return 0

        monkeypatch.setattr(
            "token_sieve.cli.estimate.run_estimate", fake_run_estimate
        )
        result = main(["estimate"])
        assert called
        assert result == 0
