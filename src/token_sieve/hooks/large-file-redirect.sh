#!/usr/bin/env bash
# PreToolUse hook: Redirect Read on large/unsupported files to appropriate tools.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
file_path=$(json_field "file_path")

# If no file path, allow
if [[ -z "$file_path" ]]; then
  exit 0
fi

# Get extension (lowercase)
ext="${file_path##*.}"
ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

# Binary extensions - always block
case "$ext" in
  bin|exe|so|dll|dylib|wasm|o|a|pyc|pyo|class)
    echo "WARNING: Binary file ($ext) cannot be meaningfully read as text. Use a hex viewer or appropriate binary tool instead." >&2
    exit 2 ;;
esac

# PDF - suggest Read with pages parameter
case "$ext" in
  pdf)
    echo "REDIRECT: Use Read with the 'pages' parameter for PDF files (e.g., pages=\"1-5\"). Reading entire PDFs wastes tokens." >&2
    exit 2 ;;
esac

# For structured text files, check line count
case "$ext" in
  yaml|yml|toml|xml|json|csv|tsv|log|conf|ini|cfg)
    # File must exist to count lines
    if [[ -f "$file_path" ]]; then
      line_count=$(wc -l < "$file_path" 2>/dev/null || echo "0")
      line_count=$(echo "$line_count" | tr -d ' ')
      if [[ "$line_count" -gt 200 ]] && [[ "${TOKEN_SIEVE_CONTEXT_MODE:-}" == "1" ]]; then
        echo "REDIRECT: File has ${line_count} lines. Use mcp__context-mode__ctx_execute_file for large structured files (auto-filtered, 98% token savings)." >&2
        exit 2
      fi
    fi
    ;;
esac

# Allow everything else
exit 0
