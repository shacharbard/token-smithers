"""Tests for edit-mcp-gate.sh — PreToolUse hook that enforces jCodeMunch
read before Edit/Write on code files.

The hook uses a state file to track which files have been accessed via
jCodeMunch. On first Edit attempt for a code file, it blocks with a
reminder. After the agent reads via jCodeMunch (recorded in state file),
subsequent Edit attempts pass through.
"""
import json
import os
import subprocess
import tempfile

import pytest

HOOK_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "token_sieve", "hooks", "edit-mcp-gate.sh",
)
HOOK_PATH = os.path.normpath(HOOK_PATH)


@pytest.fixture
def state_dir(tmp_path):
    """Provide a temp dir for MCP read state tracking."""
    return tmp_path


_TEST_SESSION_ID = "test-session"


def run_hook(tool_input: dict, state_dir: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run the edit-mcp-gate hook with given tool input."""
    payload = json.dumps({"tool_input": tool_input, "cwd": cwd or "/fake/project"})
    env = {
        **os.environ,
        "TOKEN_SIEVE_MCP_STATE_DIR": str(state_dir),
        # Simulate jCodeMunch being available
        "TOKEN_SIEVE_HAS_JCODEMUNCH": "1",
        "CLAUDE_SESSION_ID": _TEST_SESSION_ID,
    }
    return subprocess.run(
        ["bash", HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


def record_mcp_read(state_dir: str, file_path: str) -> None:
    """Simulate a jCodeMunch read by writing to the state file."""
    state_file = os.path.join(state_dir, f"jcodemunch-reads-{_TEST_SESSION_ID}")
    with open(state_file, "a") as f:
        f.write(file_path + "\n")


class TestEditMcpGate:
    """PreToolUse hook blocks Edit on code files without prior jCodeMunch read."""

    def test_blocks_edit_on_python_file_without_mcp_read(self, state_dir):
        result = run_hook(
            {"file_path": "/project/src/app/main.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 2
        assert "jCodeMunch" in result.stderr

    def test_allows_edit_after_mcp_read(self, state_dir):
        record_mcp_read(state_dir, "/project/src/app/main.py")
        result = run_hook(
            {"file_path": "/project/src/app/main.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_allows_edit_on_non_code_file(self, state_dir):
        result = run_hook(
            {"file_path": "/project/README.md", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_allows_edit_on_config_files(self, state_dir):
        result = run_hook(
            {"file_path": "/project/pyproject.toml", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_allows_edit_on_planning_files(self, state_dir):
        result = run_hook(
            {"file_path": "/project/.vbw-planning/STATE.md", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_blocks_edit_on_typescript_file(self, state_dir):
        result = run_hook(
            {"file_path": "/project/src/index.ts", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 2

    def test_blocks_edit_on_rust_file(self, state_dir):
        result = run_hook(
            {"file_path": "/project/src/main.rs", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 2

    def test_allows_when_jcodemunch_not_available(self, state_dir):
        """When jCodeMunch MCP is not available, don't block."""
        payload = json.dumps({
            "tool_input": {"file_path": "/project/src/main.py", "old_string": "x", "new_string": "y"},
            "cwd": "/fake/project",
        })
        env = {
            **os.environ,
            "TOKEN_SIEVE_MCP_STATE_DIR": str(state_dir),
            "TOKEN_SIEVE_HAS_JCODEMUNCH": "0",
        }
        result = subprocess.run(
            ["bash", HOOK_PATH],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert result.returncode == 0

    def test_allows_edit_on_test_fixtures(self, state_dir):
        result = run_hook(
            {"file_path": "/project/tests/conftest.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_allows_edit_on_init_files(self, state_dir):
        result = run_hook(
            {"file_path": "/project/src/app/__init__.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 0

    def test_allows_new_file_write(self, state_dir):
        """Write tool creates new files — allow without MCP read (file doesn't exist yet)."""
        payload = json.dumps({
            "tool_input": {"file_path": "/project/src/new_module.py", "content": "# new"},
            "tool_name": "Write",
            "cwd": "/fake/project",
        })
        env = {
            **os.environ,
            "TOKEN_SIEVE_MCP_STATE_DIR": str(state_dir),
            "TOKEN_SIEVE_HAS_JCODEMUNCH": "1",
        }
        result = subprocess.run(
            ["bash", HOOK_PATH],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        # Write for new files should be allowed (no existing code to read)
        assert result.returncode == 0

    def test_blocks_stderr_has_actionable_message(self, state_dir):
        result = run_hook(
            {"file_path": "/project/src/app/service.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        assert result.returncode == 2
        assert "get_symbol" in result.stderr or "get_file_content" in result.stderr


class TestStateFileScoping:
    """H6: State file must be scoped per session."""

    def test_state_file_uses_session_id(self, state_dir):
        """State file should include session ID in the filename."""
        env_override = {
            **os.environ,
            "TOKEN_SIEVE_MCP_STATE_DIR": str(state_dir),
            "TOKEN_SIEVE_HAS_JCODEMUNCH": "1",
            "CLAUDE_SESSION_ID": "test-session-123",
        }
        # Run the tracker to create a state file
        tracker_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "src", "token_sieve", "hooks", "mcp-read-tracker.sh",
        ))
        payload = json.dumps({
            "tool_input": {"file_path": "/project/src/main.py"},
        })
        subprocess.run(
            ["bash", tracker_path],
            input=payload,
            capture_output=True,
            text=True,
            env=env_override,
            timeout=5,
        )
        # State file should be session-scoped
        state_files = list(state_dir.iterdir()) if hasattr(state_dir, 'iterdir') else os.listdir(state_dir)
        filenames = [os.path.basename(str(f)) for f in state_files]
        assert any(
            "test-session-123" in name for name in filenames
        ), f"No session-scoped state file found. Files: {filenames}"


class TestEditGateMatchPrecision:
    """H7+H8: Edit gate matching must be precise but allow directory prefix."""

    def test_prefix_match_does_not_unlock_different_file(self, state_dir):
        """H7: Recording /foo/bar.py must NOT unlock /foo/bar_copy.py."""
        record_mcp_read(state_dir, "/project/src/app/main.py")

        result = run_hook(
            {"file_path": "/project/src/app/main_copy.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        # main_copy.py should NOT be unlocked by reading main.py (substring match)
        assert result.returncode == 2, "Substring match allowed bypass — H7 not fixed"

    def test_directory_read_unlocks_files_underneath(self, state_dir):
        """H8: Recording a directory path should unlock files under it."""
        # search_symbols records the repo path (directory), not individual files
        record_mcp_read(state_dir, "/project/src")

        result = run_hook(
            {"file_path": "/project/src/app/main.py", "old_string": "x", "new_string": "y"},
            state_dir,
        )
        # Directory prefix should unlock files underneath
        assert result.returncode == 0, "Directory prefix match failed — H8 not handled"
