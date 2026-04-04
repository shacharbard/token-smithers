#!/usr/bin/env bash
# PreToolUse hook: Redirect broad Glob patterns to jCodeMunch get_file_tree.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
pattern=$(json_field "pattern")

# If no pattern or jCodeMunch not available, allow
if [[ -z "$pattern" ]] || [[ "${TOKEN_SIEVE_JCODEMUNCH:-}" != "1" ]]; then
  exit 0
fi

# Redirect broad patterns containing **/ (recursive glob)
case "$pattern" in
  **"**/"**)
    echo "REDIRECT: Use mcp__jcodemunch__get_file_tree or mcp__jcodemunch__search_symbols instead of broad Glob patterns. jCodeMunch indexes the file tree efficiently." >&2
    exit 2 ;;
esac

# Allow specific patterns
exit 0
