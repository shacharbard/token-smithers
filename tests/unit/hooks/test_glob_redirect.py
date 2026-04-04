"""Tests for glob-redirect.sh hook."""

from __future__ import annotations


class TestGlobRedirectHook:
    """Broad glob patterns should suggest jCodeMunch get_file_tree."""

    def test_glob_large_pattern_redirects(self, run_hook):
        """Patterns like **/*.py suggest jCodeMunch get_file_tree."""
        result = run_hook(
            "glob-redirect.sh",
            {"pattern": "**/*.py"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 2
        assert "get_file_tree" in result.stderr or "search_symbols" in result.stderr

    def test_glob_recursive_star_redirects(self, run_hook):
        """Patterns containing **/ are broad and should redirect."""
        result = run_hook(
            "glob-redirect.sh",
            {"pattern": "**/test_*.py"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 2

    def test_glob_specific_pattern_allows(self, run_hook):
        """Narrow patterns like src/foo/*.py pass through."""
        result = run_hook(
            "glob-redirect.sh",
            {"pattern": "src/foo/*.py"},
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
        assert result.exit_code == 0

    def test_glob_without_jcodemunch_allows(self, run_hook):
        """Without jCodeMunch, all patterns pass through."""
        result = run_hook(
            "glob-redirect.sh",
            {"pattern": "**/*.py"},
        )
        assert result.exit_code == 0

    def test_completes_under_50ms(self, assert_completes_under_ms):
        """Hook completes in < 50ms."""
        assert_completes_under_ms(
            "glob-redirect.sh",
            {"pattern": "**/*.py"},
            max_ms=50,
            env={"TOKEN_SIEVE_JCODEMUNCH": "1"},
        )
