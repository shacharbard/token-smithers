"""Tests for webfetch-redirect.sh hook.

Blocks WebFetch tool with exit 2 and redirects to ctx_fetch_and_index.
Missing URL allows passthrough (exit 0).
"""

from __future__ import annotations


class TestWebFetchRedirectHook:
    """PreToolUse:WebFetch hook blocks with redirect to ctx_fetch_and_index."""

    def test_blocks_with_exit_2(self, run_hook):
        """WebFetch with a URL: exit 2, stderr contains REDIRECT and ctx_fetch_and_index."""
        result = run_hook(
            "webfetch-redirect.sh",
            {"tool_input": {"url": "https://example.com"}},
        )
        assert result.exit_code == 2
        assert "REDIRECT" in result.stderr
        assert "ctx_fetch_and_index" in result.stderr

    def test_missing_url_allows_passthrough(self, run_hook):
        """Missing URL field in tool_input: exit 0, passthrough."""
        result = run_hook(
            "webfetch-redirect.sh",
            {"tool_input": {}},
        )
        assert result.exit_code == 0

    def test_redirect_message_mentions_token_sieve(self, run_hook):
        """Exit 2 path includes 'token-sieve' for traceability."""
        result = run_hook(
            "webfetch-redirect.sh",
            {"tool_input": {"url": "https://docs.anthropic.com/en/docs"}},
        )
        assert result.exit_code == 2
        assert "token-sieve" in result.stderr
