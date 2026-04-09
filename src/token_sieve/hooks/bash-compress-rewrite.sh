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
# Uses python3 for JSON parsing, shell-safe quoting (shlex.quote), and
# anchored NO_COMPRESS=1 detection against the RAW command string.
#
# H5 fix: inline NO_COMPRESS detection must be computed from the raw cmd
# (not re-derived from the shlex-quoted form) and must be anchored to the
# start of the command. Unanchored detection allowed:
#   - bypass-by-filename poisoning (`pytest tests/test_NO_COMPRESS=1_x.py`)
#   - `: NO_COMPRESS=1 ; real_cmd` evasion (no-op prefix injects marker
#     while the real command runs unwrapped)
#
# Outputs three lines:
#   <shell-quoted-command>
#   <flag>          — "empty" or "present"
#   <inline-marker> — "1" if anchored NO_COMPRESS=1 at start of raw cmd, else "0"
RESULT=$(echo "$INPUT" | python3 -c "
import sys, json, shlex, re
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('')
    print('empty')
    print('0')
    sys.exit(0)

ti = d.get('tool_input', {})
cmd = ti.get('command', '')
if not cmd:
    print('')
    print('empty')
    print('0')
else:
    # shlex.quote produces a safely single-quoted string for shell use.
    print(shlex.quote(cmd))
    print('present')
    # Anchored detection on the RAW cmd: optional leading whitespace, then
    # literal 'NO_COMPRESS=1' followed by whitespace. Must be at the very
    # start — anything before it (including ':' no-op, grep args, etc.)
    # disqualifies it as a legitimate inline bypass.
    if re.match(r'^\s*NO_COMPRESS=1\s', cmd):
        print('1')
    else:
        print('0')
" 2>/dev/null) || { exit 0; }

# Parse the three-line result using pure-bash parameter expansion
# (avoids head/tail subprocesses that can trip pipefail with SIGPIPE).
QUOTED_CMD=${RESULT%%$'\n'*}
_REST=${RESULT#*$'\n'}
FLAG=${_REST%%$'\n'*}
INLINE_FLAG=${_REST#*$'\n'}

# Empty/missing command — allow passthrough
[ "$FLAG" = "empty" ] && exit 0
[ -z "$QUOTED_CMD" ] && exit 0

# D5c: inline NO_COMPRESS=1 marker (H5: anchored, computed from raw cmd).
# If present, the rewrite includes TSIEV_INLINE_NO_COMPRESS=1 so the CLI
# knows the bypass was intentional (counts toward auto-learn).
INLINE_MARKER=""
if [ "$INLINE_FLAG" = "1" ]; then
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
