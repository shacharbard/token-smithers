#!/usr/bin/env bash
# PreToolUse hook: Rewrite Bash commands to run through token-sieve compressor.
# Emits hookSpecificOutput.updatedInput.command with the D1 rewrite template:
#   TSIEV_WRAP_CMD='<ORIG>' python3 -m token_sieve compress --wrap-env
#
# Note: the correct entrypoint is `python3 -m token_sieve compress` (via __main__.py),
# NOT `python3 -m token_sieve.cli compress` (cli/ has no __main__.py).
#
# Exit 0 = allow (either rewritten or passthrough)
# Never exits 2 (bash-edge-redirect.sh runs BEFORE this in PreToolUse list;
# if it blocked, this hook is never reached).
#
# M9: Fails open — if python3 is absent or JSON is malformed, the original
# command is allowed through unmodified (no rewrite emitted).

set -euo pipefail

INPUT=$(cat 2>/dev/null || echo "")
[ -z "$INPUT" ] && exit 0

# Extract tool_input.command from the Claude Code hook JSON.
# Uses python3 for both JSON parsing and shell-safe quoting (shlex.quote).
# Outputs two lines: <shell-quoted-command>\n<raw-command-flag>
# raw-command-flag is "empty" when command was absent/empty, "present" otherwise.
RESULT=$(echo "$INPUT" | python3 -c "
import sys, json, shlex
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('')
    print('empty')
    sys.exit(0)

ti = d.get('tool_input', {})
cmd = ti.get('command', '')
if not cmd:
    print('')
    print('empty')
else:
    # shlex.quote produces a safely single-quoted string for shell use.
    # We need the raw string to embed as the env var value; shlex.quote
    # wraps it in single quotes which handles all special chars including
    # double quotes, dollar signs, backticks, and pipes.
    print(shlex.quote(cmd))
    print('present')
" 2>/dev/null) || { exit 0; }

# Parse the two-line result
QUOTED_CMD=$(echo "$RESULT" | head -1)
FLAG=$(echo "$RESULT" | tail -1)

# Empty/missing command — allow passthrough
[ "$FLAG" = "empty" ] && exit 0
[ -z "$QUOTED_CMD" ] && exit 0

# D5c: Detect inline NO_COMPRESS=1 in the command string.
# If present, the rewrite includes TSIEV_INLINE_NO_COMPRESS=1 so the CLI
# knows the bypass was intentional (counts toward auto-learn).
# The raw command (with NO_COMPRESS=1 prefix intact) is still passed via
# TSIEV_WRAP_CMD so the CLI can extract the real command and record it.
INLINE_MARKER=""
RESULT2=$(echo "$RESULT" | python3 -c "
import sys
lines = sys.stdin.read().splitlines()
# Reconstruct the raw (unquoted) command by checking if the quoted form starts with NO_COMPRESS
# We can detect by checking the first line (quoted) for NO_COMPRESS prefix indicator.
# Actually, detect from the raw command within the quoted string: look for NO_COMPRESS=1 in quoted cmd
quoted = lines[0] if lines else ''
# shlex.quote wraps in single quotes, so literal prefix is: 'NO_COMPRESS=1  (or just starts with NO_COMPRESS)
# Simpler: detect if quoted_cmd contains NO_COMPRESS=1
import re
# Match 'NO_COMPRESS=1 as prefix inside the single-quoted string (or unquoted)
if re.search(r\"NO_COMPRESS=1\s\", quoted):
    print('inline')
else:
    print('no')
" 2>/dev/null) || RESULT2="no"

if [ "$RESULT2" = "inline" ]; then
    INLINE_MARKER=" TSIEV_INLINE_NO_COMPRESS=1"
fi

# Build rewrite template (D1):
#   TSIEV_WRAP_CMD=<shell-quoted-original> python3 -m token_sieve compress --wrap-env
# When inline NO_COMPRESS=1 is detected, also export TSIEV_INLINE_NO_COMPRESS=1
REWRITTEN="TSIEV_WRAP_CMD=${QUOTED_CMD}${INLINE_MARKER} python3 -m token_sieve compress --wrap-env"

# Emit hook protocol JSON to stdout (rewrite mode).
# python3 used for reliable JSON serialization of the rewritten command string.
_TSIEV_REWRITTEN="$REWRITTEN" python3 -c "
import sys, json, os
rewritten = os.environ.get('_TSIEV_REWRITTEN', '')
out = {
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'updatedInput': {
            'command': rewritten
        }
    }
}
print(json.dumps(out))
" 2>/dev/null || exit 0

exit 0
