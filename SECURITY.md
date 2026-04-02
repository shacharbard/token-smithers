# Security Policy

## Trust Model

Token Sieve is a **local MCP compression proxy**. It runs on the user's machine, processes data in-memory, and never sends data to external services. The trust boundary is between the user's machine and their backend MCP servers.

## What Token Sieve Does NOT Do

- **Does not send data to any external service or API.** All compression is performed locally.
- **Does not execute arbitrary code from tool results.** Compression is pure string/JSON manipulation.
- **Does not modify tool call arguments.** Only tool *responses* are compressed.
- **Does not store sensitive data.** The SQLite learning database stores token counts and strategy names, not tool result content. The semantic cache stores compressed results locally with owner-only file permissions.

## Security Measures

| Measure | Detail |
|---------|--------|
| YAML parsing | `yaml.safe_load` only -- no code execution via config files |
| SQL queries | Parameterized throughout -- no SQL injection vectors |
| Temp files | Created with `0o600` permissions (owner read/write only) |
| Semantic cache | Restricted to read-only tools via allowlist; mutating tools are never cached |
| Learning store | Fails open -- I/O errors degrade gracefully without crashing tool calls |
| Compression | Pure string/JSON manipulation -- no `eval`, no `exec`, no `subprocess` |
| Assert guards | Internal None-checks use explicit `if` guards, not `assert` (safe under `python -O`) |

## Dependency Security

Core dependencies are widely audited:

- `mcp` -- Model Context Protocol SDK
- `pyyaml` -- YAML parsing (safe_load only)
- `pydantic` -- Config validation

Optional dependencies have minimal attack surface:

- `aiosqlite` -- Async SQLite (learning store, semantic cache)
- `sumy` -- Extractive summarization

Run `pip-audit` to check for known vulnerabilities in the dependency tree.

## Reporting Vulnerabilities

If you discover a security issue, please report it via:

- **GitHub Security Advisories** on this repository (preferred)
- **Email** to the repository maintainer

Please do not open public issues for security vulnerabilities.

## Security Audit Results

- **bandit**: 0 medium/high findings on 5,235 lines of source
- **pip-audit**: 0 known vulnerabilities in direct dependencies
