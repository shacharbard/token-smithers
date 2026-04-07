#!/usr/bin/env bash
# PreToolUse hook: Rewrite Bash commands to run through token-sieve compressor.
# Emits hookSpecificOutput.updatedInput.command with the D1 rewrite template:
#   TSIEV_WRAP_CMD="<ORIG>" python3 -m token_sieve.cli compress --wrap-env
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

# Build rewrite template (D1):
#   TSIEV_WRAP_CMD=<shell-quoted-original> python3 -m token_sieve.cli compress --wrap-env
REWRITTEN="TSIEV_WRAP_CMD=${QUOTED_CMD} python3 -m token_sieve.cli compress --wrap-env"

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
