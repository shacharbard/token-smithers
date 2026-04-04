#!/usr/bin/env bash
# PreToolUse hook (NotebookRead/Read): Redirect .ipynb to jDocMunch.
# Exit 0 = allow, Exit 2 = block with suggestion.
#
# Env vars:
#   TOKEN_SIEVE_HAS_JDOCMUNCH — "1" if jDocMunch is available (default: check .mcp.json)

set -euo pipefail

INPUT=$(cat 2>/dev/null || echo "{}")
[ -z "$INPUT" ] && exit 0

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
ti = d.get('tool_input', {})
print(ti.get('file_path', ''))
" 2>/dev/null || echo "")

[ -z "$FILE_PATH" ] && exit 0

# Only handle notebook files
case "$FILE_PATH" in
  *.ipynb) ;;
  *) exit 0 ;;
esac

# Check if jDocMunch is available
HAS_JDM="${TOKEN_SIEVE_HAS_JDOCMUNCH:-}"
if [ -z "$HAS_JDM" ]; then
  CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
  [ -z "$CWD" ] && CWD=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  if [ -f "$CWD/.mcp.json" ] && grep -q 'jdocmunch' "$CWD/.mcp.json" 2>/dev/null; then
    HAS_JDM="1"
  else
    HAS_JDM="0"
  fi
fi

[ "$HAS_JDM" != "1" ] && exit 0

BASENAME=$(basename "$FILE_PATH")
echo "BLOCKED: Use jDocMunch instead of NotebookRead for '$BASENAME'.
  - mcp__jdocmunch__search_sections to find specific cells by content
  - mcp__jdocmunch__get_section to retrieve a specific cell by ID
  - mcp__jdocmunch__get_toc to see notebook structure
  Index first if needed: mcp__jdocmunch__index_local" >&2
exit 2
