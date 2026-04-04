"""Tests for notebook-redirect.sh — PreToolUse hook that redirects
NotebookRead to jDocMunch for targeted cell retrieval."""
import json
import os
import subprocess

import pytest

HOOK_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "token_sieve", "hooks", "notebook-redirect.sh",
))


def run_hook(tool_input: dict, has_jdocmunch: str = "1") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "TOKEN_SIEVE_HAS_JDOCMUNCH": has_jdocmunch,
    }
    payload = json.dumps({"tool_input": tool_input, "cwd": "/fake/project"})
    return subprocess.run(
        ["bash", HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


class TestNotebookRedirect:
    def test_blocks_notebook_read_with_jdocmunch(self):
        result = run_hook({"file_path": "/project/analysis.ipynb"})
        assert result.returncode == 2
        assert "jDocMunch" in result.stderr

    def test_allows_when_jdocmunch_not_available(self):
        result = run_hook({"file_path": "/project/analysis.ipynb"}, has_jdocmunch="0")
        assert result.returncode == 0

    def test_allows_non_notebook_files(self):
        result = run_hook({"file_path": "/project/script.py"})
        assert result.returncode == 0

    def test_suggests_search_sections(self):
        result = run_hook({"file_path": "/project/data.ipynb"})
        assert result.returncode == 2
        assert "search_sections" in result.stderr or "get_section" in result.stderr

    def test_allows_when_no_file_path(self):
        result = run_hook({})
        assert result.returncode == 0
