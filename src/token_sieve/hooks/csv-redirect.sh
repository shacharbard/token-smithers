#!/usr/bin/env bash
# PreToolUse hook (Read): Redirect CSV/Excel files to jDataMunch.
# Exit 0 = allow, Exit 2 = block with suggestion.
#
# Env vars:
#   TOKEN_SIEVE_HAS_JDATAMUNCH — "1" if jDataMunch is available (default: check .mcp.json)

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

# Only handle data files
case "$FILE_PATH" in
  *.csv|*.xlsx|*.xls) ;;
  *) exit 0 ;;
esac

# Check if jDataMunch is available
HAS_JDM="${TOKEN_SIEVE_HAS_JDATAMUNCH:-}"
if [ -z "$HAS_JDM" ]; then
  CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
  [ -z "$CWD" ] && CWD=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  if [ -f "$CWD/.mcp.json" ] && grep -q 'jdatamunch' "$CWD/.mcp.json" 2>/dev/null; then
    HAS_JDM="1"
  else
    HAS_JDM="0"
  fi
fi

[ "$HAS_JDM" != "1" ] && exit 0

BASENAME=$(basename "$FILE_PATH")
echo "BLOCKED: Use jDataMunch instead of Read for '$BASENAME'.
  - mcp__jdatamunch__index_local to index the file (one-time)
  - mcp__jdatamunch__describe_dataset for schema and column profiles
  - mcp__jdatamunch__get_rows for filtered row retrieval
  - mcp__jdatamunch__aggregate for GROUP BY with count/sum/avg/min/max
  - mcp__jdatamunch__sample_rows for head/tail/random sampling" >&2
exit 2
