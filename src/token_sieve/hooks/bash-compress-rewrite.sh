#!/usr/bin/env bash
# PreToolUse hook: Rewrite Bash commands to run through token-sieve compressor.
# Emits hookSpecificOutput.updatedInput.command with the D1 rewrite template:
#   TSIEV_WRAP_CMD_ARGV='<base64-json-argv>' python3 -m token_sieve compress --wrap-env
#
# C1 fix: we emit an argv-array protocol (base64-encoded JSON list) so the
# CLI can invoke the wrapped command via subprocess.run(argv, shell=False),
# immunising the chain against shell-quoting bugs (`$()`, backticks, `;`,
# embedded quotes in filenames). If shlex.split of the original command
# fails (unterminated quote / exotic syntax), we fall through to the legacy
# TSIEV_WRAP_CMD shell-string path so existing workflows keep working.
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
# Outputs four lines:
#   <shell-quoted-command>   — legacy TSIEV_WRAP_CMD fallback value
#   <flag>                   — "empty" or "present"
#   <inline-marker>          — "1" if anchored NO_COMPRESS=1 at start of raw cmd, else "0"
#   <argv-b64>               — base64(json(argv list)) or empty if shlex.split failed
RESULT=$(echo "$INPUT" | python3 -c "
import sys, json, shlex, re, base64
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('')
    print('empty')
    print('0')
    print('')
    sys.exit(0)

ti = d.get('tool_input', {})
cmd = ti.get('command', '')
if not cmd:
    print('')
    print('empty')
    print('0')
    print('')
else:
    print(shlex.quote(cmd))
    print('present')
    if re.match(r'^\s*NO_COMPRESS=1\s', cmd):
        print('1')
    else:
        print('0')
    # C1: argv-array protocol. shlex.split(cmd, posix=True) gives us the
    # argv list the user intended. If parsing fails (unterminated quote,
    # exotic syntax), emit an empty argv so the bash caller falls through
    # to the legacy TSIEV_WRAP_CMD shell-string path.
    try:
        argv = shlex.split(cmd, posix=True)
        if argv:
            encoded = base64.b64encode(json.dumps(argv).encode('utf-8')).decode('ascii')
            print(encoded)
        else:
            print('')
    except ValueError:
        print('')
" 2>/dev/null) || { exit 0; }

# Parse the four-line result using pure-bash parameter expansion.
# M13 invariant: do NOT introduce `head`/`tail` pipes here. Under
# `set -euo pipefail` they can exit 141 (SIGPIPE) on early pipe close,
# which `set -e` would propagate and block legitimate commands.
QUOTED_CMD=${RESULT%%$'\n'*}
_REST=${RESULT#*$'\n'}
FLAG=${_REST%%$'\n'*}
_REST2=${_REST#*$'\n'}
INLINE_FLAG=${_REST2%%$'\n'*}
ARGV_B64=${_REST2#*$'\n'}
# If there's no 4th line (older python path), ARGV_B64 may equal INLINE_FLAG
# due to the parameter expansion fallback. Guard against that.
if [ "$ARGV_B64" = "$INLINE_FLAG" ]; then
    ARGV_B64=""
fi

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

# Build rewrite template (D1 + C1):
#   Preferred (argv protocol, shlex.split succeeded):
#     TSIEV_WRAP_CMD_ARGV='<b64>' python3 -m token_sieve compress --wrap-env
#   Legacy (shlex.split failed or argv empty):
#     TSIEV_WRAP_CMD=<shell-quoted-original> python3 -m token_sieve compress --wrap-env
# When inline NO_COMPRESS=1 is detected, also export TSIEV_INLINE_NO_COMPRESS=1
if [ -n "$ARGV_B64" ]; then
    REWRITTEN="TSIEV_WRAP_CMD_ARGV='${ARGV_B64}'${INLINE_MARKER} python3 -m token_sieve compress --wrap-env"
else
    REWRITTEN="TSIEV_WRAP_CMD=${QUOTED_CMD}${INLINE_MARKER} python3 -m token_sieve compress --wrap-env"
fi

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
