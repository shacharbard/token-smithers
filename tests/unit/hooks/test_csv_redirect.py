"""Tests for csv-redirect.sh — PreToolUse hook that redirects
Read on CSV/Excel files to jDataMunch."""
import json
import os
import subprocess

import pytest

HOOK_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "token_sieve", "hooks", "csv-redirect.sh",
))


def run_hook(tool_input: dict, has_jdatamunch: str = "1") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "TOKEN_SIEVE_HAS_JDATAMUNCH": has_jdatamunch,
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


class TestCsvRedirect:
    def test_blocks_csv_read_with_jdatamunch(self):
        result = run_hook({"file_path": "/project/data.csv"})
        assert result.returncode == 2
        assert "jDataMunch" in result.stderr

    def test_blocks_xlsx_read(self):
        result = run_hook({"file_path": "/project/report.xlsx"})
        assert result.returncode == 2
        assert "jDataMunch" in result.stderr

    def test_blocks_xls_read(self):
        result = run_hook({"file_path": "/project/legacy.xls"})
        assert result.returncode == 2
        assert "jDataMunch" in result.stderr

    def test_allows_when_jdatamunch_not_available(self):
        result = run_hook({"file_path": "/project/data.csv"}, has_jdatamunch="0")
        assert result.returncode == 0

    def test_allows_non_data_files(self):
        result = run_hook({"file_path": "/project/main.py"})
        assert result.returncode == 0

    def test_allows_json_files(self):
        result = run_hook({"file_path": "/project/config.json"})
        assert result.returncode == 0

    def test_suggests_index_and_describe(self):
        result = run_hook({"file_path": "/project/data.csv"})
        assert result.returncode == 2
        assert "index_local" in result.stderr
        assert "describe_dataset" in result.stderr

    def test_allows_when_no_file_path(self):
        result = run_hook({})
        assert result.returncode == 0
