#!/usr/bin/env bash
# PreToolUse hook (Agent): Block subagent spawns if prompt lacks MCP tool guidance.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
prompt=$(json_field "prompt")
agent_type=$(json_field "agent_type")

# Exempt agent types
case "$agent_type" in
  claude-code-guide|Explore)
    exit 0 ;;
esac

# Short prompts (< 300 chars) are simple queries, exempt
if [[ ${#prompt} -lt 300 ]]; then
  exit 0
fi

# Explicit exemption tag
if echo "$prompt" | grep -q "# mcp-exempt" 2>/dev/null; then
  exit 0
fi

# Check for any MCP tool keyword (single grep with alternation for speed)
if echo "$prompt" | grep -qE "mcp__jcodemunch__|mcp__jdocmunch__|mcp__jdatamunch__|mcp__context-mode__|jCodeMunch|jDocMunch|jDataMunch|ctx_execute|get_symbol|search_symbols|get_section|search_sections" 2>/dev/null; then
  exit 0
fi

# No MCP guidance found — block
cat >&2 <<'BLOCKED_MSG'
BLOCKED: Subagent prompt must include MCP tool guidance for token savings.
Add these instructions to the prompt:
- Code files: use mcp__jcodemunch__search_symbols and mcp__jcodemunch__get_symbol_source instead of Read
- Doc files: use mcp__jdocmunch__search_sections and mcp__jdocmunch__get_section instead of Read
- Large output: use mcp__context-mode__ctx_execute instead of Bash
- Data files: use mcp__jdatamunch__* tools instead of Read on CSV/Excel
BLOCKED_MSG
exit 2
