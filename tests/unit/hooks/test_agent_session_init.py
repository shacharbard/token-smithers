"""Tests for agent-session-init.sh hook."""

from __future__ import annotations


class TestAgentSessionInitHook:
    """SessionStart hook detects agent context and outputs MCP rules."""

    def test_agent_session_outputs_rules(self, run_hook):
        """When CLAUDE_AGENT_ID is set, outputs MCP navigation rules."""
        result = run_hook(
            "agent-session-init.sh",
            {},
            env={"CLAUDE_AGENT_ID": "test-agent-123"},
        )
        assert result.exit_code == 0  # SessionStart should never block
        assert "MCP" in result.stdout or "mcp" in result.stdout.lower()

    def test_human_session_minimal(self, run_hook):
        """When CLAUDE_AGENT_ID is not set, outputs minimal or empty."""
        result = run_hook(
            "agent-session-init.sh",
            {},
        )
        assert result.exit_code == 0
        # Human sessions should have minimal/no output
        assert len(result.stdout.strip()) < 50

    def test_rules_contain_jcodemunch(self, run_hook):
        """Agent output mentions jCodeMunch for code files."""
        result = run_hook(
            "agent-session-init.sh",
            {},
            env={"CLAUDE_AGENT_ID": "dev-agent"},
        )
        assert "jCodeMunch" in result.stdout or "jcodemunch" in result.stdout.lower()

    def test_rules_contain_jdocmunch(self, run_hook):
        """Agent output mentions jDocMunch for docs."""
        result = run_hook(
            "agent-session-init.sh",
            {},
            env={"CLAUDE_AGENT_ID": "dev-agent"},
        )
        assert "jDocMunch" in result.stdout or "jdocmunch" in result.stdout.lower()

    def test_rules_contain_ctx_execute(self, run_hook):
        """Agent output mentions ctx_execute for Bash."""
        result = run_hook(
            "agent-session-init.sh",
            {},
            env={"CLAUDE_AGENT_ID": "dev-agent"},
        )
        assert "ctx_execute" in result.stdout

    def test_parent_session_also_triggers(self, run_hook):
        """CLAUDE_PARENT_SESSION_ID also triggers agent rules."""
        result = run_hook(
            "agent-session-init.sh",
            {},
            env={"CLAUDE_PARENT_SESSION_ID": "parent-sess-456"},
        )
        assert result.exit_code == 0
        assert "MCP" in result.stdout or "jCodeMunch" in result.stdout

    def test_completes_under_50ms(self, assert_completes_under_ms):
        """Hook completes in < 50ms."""
        assert_completes_under_ms(
            "agent-session-init.sh",
            {},
            max_ms=50,
            env={"CLAUDE_AGENT_ID": "test-agent"},
        )
