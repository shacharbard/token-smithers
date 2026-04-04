#!/usr/bin/env bash
# PreToolUse hook: Redirect verbose CLI commands to ctx_execute.
# Exit 0 = allow, Exit 2 = block with suggestion.

source "$(dirname "$0")/_common.sh"

read_stdin
command=$(json_field "command")

# If no command or context-mode not available, allow
if [[ -z "$command" ]] || [[ "${TOKEN_SIEVE_CONTEXT_MODE:-}" != "1" ]]; then
  exit 0
fi

# Extract the base command (first word or first two words for compound cmds)
case "$command" in
  "docker logs"*|"docker-compose logs"*)
    echo "REDIRECT: Use mcp__context-mode__ctx_execute instead of Bash for 'docker logs'. Large output is auto-filtered (98% token savings)." >&2
    exit 2 ;;
  "kubectl logs"*|"kubectl describe"*)
    echo "REDIRECT: Use mcp__context-mode__ctx_execute instead of Bash for kubectl verbose commands. Large output is auto-filtered." >&2
    exit 2 ;;
  "terraform plan"*|"terraform apply"*)
    echo "REDIRECT: Use mcp__context-mode__ctx_execute instead of Bash for terraform commands. Large output is auto-filtered." >&2
    exit 2 ;;
  "helm template"*|"helm install"*|"helm upgrade"*)
    echo "REDIRECT: Use mcp__context-mode__ctx_execute instead of Bash for helm commands. Large output is auto-filtered." >&2
    exit 2 ;;
esac

# Allow all other commands
exit 0
