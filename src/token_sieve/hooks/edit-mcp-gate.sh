#!/usr/bin/env bash
# PreToolUse hook (Edit/Write): Enforce jCodeMunch read before editing code files.
# Uses a state file to track files accessed via jCodeMunch.
# Exit 0 = allow, Exit 2 = block with suggestion.
#
# Env vars:
#   TOKEN_SIEVE_MCP_STATE_DIR  — directory for state files (default: /tmp)
#   TOKEN_SIEVE_HAS_JCODEMUNCH — "1" if jCodeMunch is available (default: check .mcp.json)

set -euo pipefail

# M9: Hooks intentionally fail-open (exit 0) when python3 is absent or JSON
# parsing fails. This is a deliberate availability-over-security design:
# blocking tool use because of a missing interpreter would break the agent's
# workflow entirely. The hooks are advisory guardrails, not security gates.
INPUT=$(cat 2>/dev/null || echo "{}")
[ -z "$INPUT" ] && exit 0

# M10 fix: consolidate 3 python3 invocations into 1 for all JSON field extraction
read -r FILE_PATH TOOL_NAME CWD_FIELD <<< "$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('  ')
    sys.exit(0)
ti = d.get('tool_input', {})
file_path = ti.get('file_path', '')
tool_name = d.get('tool_name', '')
cwd = d.get('cwd', '')
print(f'{file_path} {tool_name} {cwd}')
" 2>/dev/null || echo "  ")"

# No file path — allow
[ -z "$FILE_PATH" ] && exit 0

# Check if jCodeMunch is available
HAS_JCM="${TOKEN_SIEVE_HAS_JCODEMUNCH:-}"
if [ -z "$HAS_JCM" ]; then
  CWD="$CWD_FIELD"
  if [ -z "$CWD" ] && [[ "$FILE_PATH" = /* ]]; then
    _DIR=$(dirname "$FILE_PATH")
    while [ "$_DIR" != "/" ]; do
      [ -f "$_DIR/.mcp.json" ] && CWD="$_DIR" && break
      _DIR=$(dirname "$_DIR")
    done
  fi
  [ -z "$CWD" ] && CWD=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  if [ -f "$CWD/.mcp.json" ] && grep -q 'jcodemunch' "$CWD/.mcp.json" 2>/dev/null; then
    HAS_JCM="1"
  else
    HAS_JCM="0"
  fi
fi

# If jCodeMunch not available, allow everything
[ "$HAS_JCM" != "1" ] && exit 0

BASENAME=$(basename "$FILE_PATH")

# Check if file is a code type supported by jCodeMunch
is_code_file() {
  case "$1" in
    *.py|*.ts|*.tsx|*.js|*.jsx|*.go|*.rs|*.java|*.php|*.dart|*.cs|*.c|*.cpp|*.h|*.hpp|\
    *.swift|*.ex|*.exs|*.rb|*.pl|*.pm|*.gd|*.kt|*.scala|*.hs|*.jl|*.r|*.R|*.lua|*.sh|\
    *.css|*.sql|*.vue|*.groovy|*.m|*.proto|*.hcl|*.graphql|*.nix|*.asm)
      return 0 ;;
    *) return 1 ;;
  esac
}

# Non-code files — allow
is_code_file "$BASENAME" || exit 0

# Exceptions: small/boilerplate files that don't need MCP navigation
case "$BASENAME" in
  __init__.py|conftest.py|CLAUDE.md) exit 0 ;;
esac

# Planning/config directories — allow
case "$FILE_PATH" in
  */.vbw-planning/*|*/.planning/*|*/.claude/*) exit 0 ;;
esac

# Write tool for new files (has "content" but no "old_string") — allow
if [ "$TOOL_NAME" = "Write" ]; then
  HAS_OLD=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('yes' if 'old_string' in d.get('tool_input', {}) else 'no')
" 2>/dev/null)
  [ "$HAS_OLD" = "no" ] && exit 0
fi

# Check state file for prior jCodeMunch read
# H6 fix: scope state file per session using CLAUDE_SESSION_ID
STATE_DIR="${TOKEN_SIEVE_MCP_STATE_DIR:-/tmp}"
SESSION_ID="${CLAUDE_SESSION_ID:-default}"
STATE_FILE="$STATE_DIR/jcodemunch-reads-${SESSION_ID}"

if [ -f "$STATE_FILE" ]; then
  # H7 fix: use grep -qxF (exact full-line match) to prevent suffix bypass.
  # E.g., recording /foo/bar.py must NOT unlock /foo/bar.py.bak.
  if grep -qxF "$FILE_PATH" "$STATE_FILE" 2>/dev/null; then
    exit 0
  fi

  # H8 design: For search_symbols, the tracker records the repo path (a
  # directory), not individual files. We intentionally allow prefix matching
  # for directory paths — a directory read unlocks all files under it.
  # This uses grep -qF (substring match) but only against the file path's
  # directory components, not the full line.
  DIR_PATH=$(dirname "$FILE_PATH")
  while [ "$DIR_PATH" != "/" ] && [ "$DIR_PATH" != "." ]; do
    if grep -qxF "$DIR_PATH" "$STATE_FILE" 2>/dev/null; then
      exit 0
    fi
    DIR_PATH=$(dirname "$DIR_PATH")
  done
fi

# Block with actionable message
echo "BLOCKED: Use jCodeMunch to read '$BASENAME' before editing.
  - mcp__jcodemunch__get_symbol to understand the function/class
  - mcp__jcodemunch__get_file_content(start_line=N, end_line=M) for the edit region
  - Then retry your Edit with the correct context
  Read is only allowed for: non-code files, __init__.py, conftest.py, or files <50 lines" >&2
exit 2
