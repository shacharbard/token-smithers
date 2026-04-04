#!/usr/bin/env bash
# PreToolUse hook: Redirect Grep to jCodeMunch search_text for code directories.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
path=$(json_field "path")

# If no path or jCodeMunch not available, allow
if [[ -z "$path" ]] || [[ "${TOKEN_SIEVE_JCODEMUNCH:-}" != "1" ]]; then
  exit 0
fi

# Allow Grep on non-code directories
if ! is_code_path "$path"; then
  exit 0
fi

# Redirect to jCodeMunch
echo "REDIRECT: Use mcp__jcodemunch__search_text or mcp__jcodemunch__search_symbols instead of Grep for code searches. jCodeMunch indexes code and saves 85-95% tokens." >&2
exit 2
