#!/usr/bin/env bash
# SessionStart hook: Detect agent context and inject MCP navigation rules.
# Always exits 0 (SessionStart hooks should never block).

source "$(dirname "$0")/_common.sh"

read_stdin

# Detect agent context via env vars
if [[ -n "${CLAUDE_AGENT_ID:-}" ]] || [[ -n "${CLAUDE_PARENT_SESSION_ID:-}" ]]; then
  cat <<'AGENT_RULES'
SPAWNED AGENT — MCP Tool Navigation Rules:
- Code files (.py/.ts/.js/.go/.rs/.java): use jCodeMunch (search_symbols, get_symbol_source) NOT Read
- Doc files (.md/.rst/.adoc): use jDocMunch (search_sections, get_section) NOT Read
- Data files (.csv/.xlsx): use jDataMunch (index_local, get_rows) NOT Read
- Large Bash output (tests, git log, builds): use ctx_execute NOT Bash
- Small files (<50 lines), CLAUDE.md, config files: Read is OK
AGENT_RULES
fi

exit 0
