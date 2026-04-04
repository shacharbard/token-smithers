"""Tests for agent-mcp-gate.sh hook."""

from __future__ import annotations


class TestAgentMcpGateHook:
    """Subagent prompts must include MCP tool guidance."""

    def test_prompt_with_jcodemunch_allows(self, run_hook):
        """Prompt containing mcp__jcodemunch__search_symbols passes."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "Use mcp__jcodemunch__search_symbols to find the function definition in the codebase. " * 3},
        )
        assert result.exit_code == 0

    def test_prompt_with_jdocmunch_allows(self, run_hook):
        """Prompt containing mcp__jdocmunch__search_sections passes."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "Use mcp__jdocmunch__search_sections to find documentation. Read carefully. " * 3},
        )
        assert result.exit_code == 0

    def test_prompt_with_ctx_execute_allows(self, run_hook):
        """Prompt containing mcp__context-mode__ctx_execute passes."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "Always use mcp__context-mode__ctx_execute instead of Bash for large output. Be thorough. " * 3},
        )
        assert result.exit_code == 0

    def test_prompt_with_get_symbol_allows(self, run_hook):
        """Prompt containing get_symbol (shorter keyword) passes."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "When navigating code, use get_symbol to read specific functions. Do not read entire files. " * 3},
        )
        assert result.exit_code == 0

    def test_prompt_without_mcp_blocks(self, run_hook):
        """Prompt without any MCP tool names exits 2 with instructions."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "Please read the file at src/main.py and understand the code structure. Analyze all imports and function definitions carefully. " * 3},
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.stderr
        assert "jcodemunch" in result.stderr.lower() or "jCodeMunch" in result.stderr

    def test_short_prompt_exempt(self, run_hook):
        """Prompts < 300 chars pass through without MCP check."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "Fix the bug in line 42."},
        )
        assert result.exit_code == 0

    def test_exempt_agent_types(self, run_hook):
        """Agent types like claude-code-guide pass through."""
        for agent_type in ["claude-code-guide", "Explore"]:
            result = run_hook(
                "agent-mcp-gate.sh",
                {"prompt": "This is a long prompt without any MCP tools. " * 10,
                 "agent_type": agent_type},
            )
            assert result.exit_code == 0, f"Expected allow for agent type: {agent_type}"

    def test_mcp_exempt_tag(self, run_hook):
        """Prompts containing # mcp-exempt pass through."""
        result = run_hook(
            "agent-mcp-gate.sh",
            {"prompt": "# mcp-exempt\nThis is a long prompt that does not mention MCP tools. " * 5},
        )
        assert result.exit_code == 0

    def test_completes_under_50ms(self, assert_completes_under_ms):
        """Hook completes in < 50ms."""
        assert_completes_under_ms(
            "agent-mcp-gate.sh",
            {"prompt": "Test prompt without MCP tools but quite long. " * 10},
            max_ms=50,
        )
