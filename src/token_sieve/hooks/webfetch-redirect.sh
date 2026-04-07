#!/usr/bin/env bash
# PreToolUse hook: Block WebFetch and redirect to ctx_fetch_and_index.
# Exit 0 = allow (missing/empty URL — passthrough)
# Exit 2 = block with redirect message (D20)
#
# Decision D20: WebFetch is redirected to mcp__context-mode__ctx_fetch_and_index
# which auto-indexes fetched content and filters large pages (98% token savings).
#
# M9: Fails open — if python3 is absent or JSON malformed, allows through.

set -euo pipefail

INPUT=$(cat 2>/dev/null || echo "")
[ -z "$INPUT" ] && exit 0

# Extract tool_input.url from the Claude Code hook JSON.
URL=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('')
    sys.exit(0)
ti = d.get('tool_input', {})
print(ti.get('url', ''))
" 2>/dev/null) || exit 0

# Missing or empty URL — allow passthrough
[ -z "$URL" ] && exit 0

# Block with redirect message (D20)
echo "REDIRECT (token-sieve): Use mcp__context-mode__ctx_fetch_and_index instead of WebFetch — output is auto-indexed, large pages auto-filtered (98% token savings)." >&2
exit 2
