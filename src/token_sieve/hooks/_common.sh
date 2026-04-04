#!/usr/bin/env bash
# Shared helpers for token-sieve PreToolUse redirect hooks.
# Source this file: source "$(dirname "$0")/_common.sh"

set -euo pipefail

# Read stdin into HOOK_INPUT (call once per hook).
# Uses cat to handle both piped and subprocess stdin reliably.
read_stdin() {
  HOOK_INPUT=$(cat 2>/dev/null) || HOOK_INPUT=""
}

# Extract a JSON string field using python3 one-liner.
# Usage: value=$(json_field "field_name")
# Returns empty string if field missing or input is not valid JSON.
json_field() {
  local field="$1"
  _HOOK_JSON="$HOOK_INPUT" _HOOK_FIELD="$field" python3 -c "
import os, json
try:
    d = json.loads(os.environ.get('_HOOK_JSON', ''))
    print(d.get(os.environ['_HOOK_FIELD'], ''))
except Exception:
    print('')
" 2>/dev/null || echo ""
}

# Check if path looks like a code project directory (not system/config dirs).
is_code_path() {
  local path="$1"
  case "$path" in
    /etc/*|/var/*|/tmp/*|/dev/*|/proc/*|/sys/*|/usr/share/*|/opt/homebrew/*)
      return 1 ;;
  esac
  return 0
}

# MCP tool keywords for subagent prompt validation.
MCP_KEYWORDS=(
  "mcp__jcodemunch__"
  "mcp__jdocmunch__"
  "mcp__jdatamunch__"
  "mcp__context-mode__"
  "jCodeMunch"
  "jDocMunch"
  "jDataMunch"
  "ctx_execute"
  "get_symbol"
  "search_symbols"
  "get_section"
  "search_sections"
)

# Image extensions (bitmap formats that are token-heavy).
IMAGE_EXTENSIONS="png|jpg|jpeg|gif|webp|bmp|tiff"

# Binary extensions that should never be read.
BINARY_EXTENSIONS="bin|exe|so|dll|dylib|wasm|o|a|pyc|pyo|class"
