"""Tests for grep-redirect.sh hook."""

from __future__ import annotations


class TestGrepRedirectHook:
    """Grep on code directories should suggest jCodeMunch search_text."""

    def test_grep_code_directory_redirects(self, run_hook):
        """Grep on a path within a code project suggests jCodeMunch."""
        result = run_hook(
            "grep-redirect.sh",
            {"pattern": "def foo", "path": "/home/user/project/src"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 2
        assert "search_text" in result.stderr or "search_symbols" in result.stderr

    def test_grep_non_code_allows(self, run_hook):
        """Grep on /etc/ or non-code directories passes through."""
        result = run_hook(
            "grep-redirect.sh",
            {"pattern": "error", "path": "/etc/nginx"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 0

    def test_grep_without_jcodemunch_allows(self, run_hook):
        """When jCodeMunch is not available, Grep passes through."""
        result = run_hook(
            "grep-redirect.sh",
            {"pattern": "def foo", "path": "/home/user/project/src"},
            # No TOKEN_SIEVE_JCODEMUNCH env var
        )
        assert result.exit_code == 0

    def test_exit_code_and_message(self, run_hook):
        """Exit code is 2 and stderr contains the redirect suggestion."""
        result = run_hook(
            "grep-redirect.sh",
            {"pattern": "class MyClass", "path": "/home/user/project/src"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 2
        assert "jcodemunch" in result.stderr.lower() or "jCodeMunch" in result.stderr

    def test_completes_under_50ms(self, assert_completes_under_ms):
        """Hook completes in < 50ms."""
        assert_completes_under_ms(
            "grep-redirect.sh",
            {"pattern": "foo", "path": "/home/user/project"},
            max_ms=50,
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
