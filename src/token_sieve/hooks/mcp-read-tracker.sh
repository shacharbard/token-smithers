#!/usr/bin/env bash
# PostToolUse hook: Track files accessed via jCodeMunch MCP tools.
# Records file paths to a state file consumed by edit-mcp-gate.sh.
# Always exits 0 (PostToolUse hooks should never block).
#
# Matcher: mcp__jcodemunch__get_symbol|mcp__jcodemunch__get_file_content|mcp__jcodemunch__search_symbols

set -euo pipefail

INPUT=$(cat 2>/dev/null || echo "{}")
[ -z "$INPUT" ] && exit 0

# H6 fix: scope state file per session using CLAUDE_SESSION_ID to prevent
# cross-session bleed and unbounded growth.
STATE_DIR="${TOKEN_SIEVE_MCP_STATE_DIR:-/tmp}"
SESSION_ID="${CLAUDE_SESSION_ID:-default}"
STATE_FILE="$STATE_DIR/jcodemunch-reads-${SESSION_ID}"

# Extract file path from tool input (varies by MCP tool)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
ti = d.get('tool_input', {})
path = ti.get('path', '') or ti.get('file_path', '') or ti.get('repo', '')
print(path)
" 2>/dev/null || echo "")

if [ -n "$FILE_PATH" ]; then
  mkdir -p "$STATE_DIR"
  # H6 fix: use flock to prevent race conditions on concurrent appends
  (
    flock -x 200
    # Deduplicate: only append if not already present
    grep -qxF "$FILE_PATH" "$STATE_FILE" 2>/dev/null || echo "$FILE_PATH" >> "$STATE_FILE"
  ) 200>>"$STATE_FILE"
fi

exit 0
