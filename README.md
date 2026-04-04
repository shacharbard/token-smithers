# Token Smithers

*"Your context window is a fortune. Stop squandering it."*

```
Claude Code  <-->  Token Smithers (proxy)  <-->  Backend MCP Server
```

Your loyal assistant for token efficiency. Token Smithers sits between Claude Code and your backend MCP servers, transparently compressing tool schemas and results to reduce token usage. No changes to Claude Code or your backend servers required.

Like any good assistant, Smithers does the dirty work silently — and reports back with style.

**Works with any MCP client** — Claude Code, Codex, Cursor, Windsurf, Cline, or anything that speaks the MCP protocol. Not tied to any specific tool.

> **Note:** Token Smithers currently supports **stdio MCP servers** (servers launched as a subprocess). HTTP/remote MCP servers (e.g., servers connected via URL) are not yet supported. Most MCP servers use stdio — check your config for `"type": "stdio"` or `"command"` entries.
>
> **Single-instance servers:** Some MCP servers lock their database and only allow one running instance (e.g., MuninnDB). Since Token Smithers spawns the backend as a subprocess, these servers will fail if another instance is already running. Leave single-instance servers unwrapped.

## Which MCP Servers Should I Wrap?

Each MCP server is an independent backend. Your AI coding tool talks to each one separately — they don't share traffic with each other:

```
                    ┌──→  MCP Server A  (filesystem — raw data)
                    │
Your AI Tool  ──────┼──→  MCP Server B  (GitHub — raw API responses)
                    │
                    ├──→  MCP Server C  (database — query results)
                    │
                    └──→  MCP Server D  (code intelligence — already optimized)
```

Token Smithers wraps **one server at a time**. You choose which ones benefit from compression:

| Server type | Wrap? | Why |
|------------|-------|-----|
| **Filesystem / file servers** | **Yes** | Returns entire files raw — big savings |
| **GitHub / API servers** | **Yes** | Returns verbose JSON API responses |
| **Database / query servers** | **Yes** | Returns raw query results |
| **General-purpose servers** | **Yes** | Most MCP servers return unoptimized data |
| **Already-optimized servers** (e.g., jCodeMunch, jDocMunch, context-mode) | **Yes — for schemas** | Results are already minimal, but their **tool schemas still load raw** every refresh. Wrapping saves ~55% on schema tokens without interfering with their internal optimization. Servers with many tools (e.g., jCodeMunch: 31 tools) benefit most. |

**Rule of thumb:** if the MCP server dumps raw data, wrap it for both schema and result savings. If it already returns compact results, wrap it anyway — you still save on schema loading, which happens every `tools/list` refresh (~5 times per session).

`token-smithers setup` shows all your servers and lets you pick. You can always undo with `token-smithers setup --undo`.

### Built-in tools vs MCP servers

AI coding tools like Claude Code have **built-in tools** (Read, Edit, Grep, Bash) that don't go through MCP. Token Smithers can only compress MCP server traffic — not built-in tool calls.

| Tool | Type | Token Smithers? |
|------|------|:-:|
| Read, Edit, Grep, Bash, Write, Glob | Built-in | -- |
| Filesystem MCP, GitHub MCP, database MCP | MCP server | Yes |
| Already-optimized MCPs (jCodeMunch, jDocMunch, context-mode) | MCP server | Yes — for schemas |

**If you use standard MCP servers** (filesystem, GitHub, database, etc.) that return raw uncompressed data, Token Smithers gives the biggest savings — up to 62% across all content types.

**If you already use optimization tools** like jCodeMunch, jDocMunch, or context-mode, those handle most of the heavy lifting for code reads, doc reads, and command output. Token Smithers still adds value for schema virtualization (compressing tool definitions) and for MCP servers those tools don't cover — API servers (GitHub, EXA), memory stores (Muninn), documentation fetchers (context7), and any future MCP server you add.

## Savings by MCP Server

Measured on realistic schemas and responses for popular MCP servers:

| MCP Server | Tools | Schema saved | Result saved | Where savings come from |
|-----------|------:|:------------:|:------------:|------------------------|
| **context7** | 2 | **64%** | low | Schema virtualization (DietMCP notation) |
| **EXA (search)** | 3 | 25% | **42%** | Search result JSON compression |
| **GitHub MCP** | 10 | **33%** | **25%** | Null fields, timestamps, repeated structures |
| **Filesystem MCP** | 8 | **41%** | **41%** | Path dedup, null fields, file listing arrays |
| **Muninn** | 10 | **38%** | **52%** | Memory recall JSON, entity lists |
| **jCodeMunch** | 31 | **~55%** | — | Schema-only: 31 tools with rich params (large `language` enum). Results already optimized internally |
| **jDocMunch** | 11 | **~55%** | — | Schema-only: results already optimized internally |
| **context-mode** | 9 | **~55%** | — | Schema-only: results already optimized internally |
| **jDataMunch** | 11 | **~55%** | — | Schema-only: results already optimized internally |

### Per-session impact

Every MCP server you have loaded costs tokens on **every `tools/list` refresh** — even if you never call those tools. With 9 MCP servers (95 tools total, including already-optimized ones):

| | Without Smithers | With Smithers | Saved |
|--|--:|--:|--:|
| Per tools/list refresh | ~12,000 tokens | ~5,400 tokens | **~6,600 tokens (55%)** |
| Per session (~5 refreshes) | ~60,000 tokens | ~27,000 tokens | **~33,000 tokens** |
| + 10 tool calls | ~110,000 tokens | ~52,000 tokens | **~58,000 tokens** |

Even "already-optimized" MCP servers like jCodeMunch (31 tools) cost ~5,350 schema tokens per refresh. Wrapping them saves ~55% on schemas alone — **~25,500 tokens per session** — without affecting their internal result optimization.

The more MCP servers you have, the more schema overhead you pay per refresh — and the more Token Smithers saves.

## What It Does

| Feature | What happens | Token savings |
|---------|-------------|---------------|
| **Cleanup layer** | Strips whitespace, null fields, redundant paths, timestamps | 10-30% |
| **Content-aware compression** | Routes content to specialized compressors (JSON tables, logs, code, graphs) | 20-60% |
| **Schema virtualization** | Compresses tool schemas to DietMCP one-liner notation | 60-80% |
| **Semantic caching** | Returns cached results for similar read-only tool calls | 100% (cache hits) |
| **Deduplication** | Detects repeated tool results within a session | 100% (dedup hits) |
| **Progressive disclosure** | Returns summaries for oversized results, full content on demand | 83-98% |
| **Key aliasing** | Replaces repeated long JSON keys with short aliases | 20-40% |
| **AST skeleton** | Extracts function signatures from Python source, drops bodies | 50-80% |
| **System prompt compression** | Compresses backend server instructions at startup | 15-30% |

## How It Works

1. **Claude Code calls a tool** via MCP → Token Smithers receives the request
2. **Safety check**: Mutating tools (write, delete, create) always go to backend — never cached
3. **Cache check**: Read-only tools checked against semantic cache for similar prior results
4. **Backend call**: Request forwarded to your backend MCP server
5. **Compression pipeline**: Result passes through the adapter chain (cleanup → content-specific → safety net)
6. **Response**: Compressed result returned to Claude Code
7. **Learning**: Usage stats and compression events recorded for cross-session optimization

## Benchmarks

Measured across 12 content types at 3 sizes each, through the full 11-adapter pipeline. **Total: 192K tokens in, 73K out — 62% saved.**

| Content Type | Small | Medium | Large | Key Strategies |
|-------------|------:|-------:|------:|---------------|
| JSON array (file listing) | 45% | 46% | 46% | NullFieldElider, PathDedup |
| JSON API response (PRs) | 24% | 25% | 25% | NullFieldElider, TimestampNormalizer |
| JSON nested config | 27% | 27% | 27% | NullFieldElider, WhitespaceNormalizer |
| JSON repeated keys | 21% | 22% | 22% | KeyAliasing, NullFieldElider |
| Python source code | 58% | **84%** | **95%** | ASTSkeletonExtractor |
| Log output | 20% | **72%** | **94%** | TimestampNormalizer, SmartTruncation |
| Error stack traces | 10% | 32% | **77%** | PathDedup, SmartTruncation |
| Dependency graph | 34% | **69%** | **89%** | GraphAdjacencyEncoder, YamlTranscoder |
| Git diff output | 0% | **68%** | **89%** | PathDedup, SmartTruncation |
| Markdown documentation | 14% | **74%** | **91%** | SmartTruncation |
| CSV/tabular data | 0% | **66%** | **93%** | SmartTruncation |
| XML configuration | 47% | **82%** | **93%** | NullFieldElider, SmartTruncation |

Pipeline latency: **0.05 - 11ms** depending on content size. A typical MCP tool call takes 50-500ms, so Token Smithers adds **less than 1% overhead**.

<details>
<summary>Why so fast</summary>

- Pure string manipulation, regex, and JSON parse/serialize — no ML, no GPU
- Content-aware routing skips irrelevant adapters
- Small results (<2000 tokens) skip the pipeline entirely via the size gate
- No network calls — everything runs in-process
- Semantic cache fuzzy lookup adds 1-5ms when enabled; exact-match is O(1)

</details>

<details>
<summary>Reproduce these benchmarks</summary>

```bash
python scripts/benchmark_all.py
```

</details>

## Requirements

- **Python 3.11+**
- **A backend MCP server** — any MCP-compatible server that Token Smithers will proxy to (e.g., filesystem, GitHub, database, or custom servers)

## Installation

**macOS / Linux:**

```bash
pip install "token-smithers[learning] @ git+https://github.com/shacharbard/token-smithers.git@stable"
```

Or with `pipx` (isolated, no venv needed):

```bash
pipx install "token-smithers[learning] @ git+https://github.com/shacharbard/token-smithers.git@stable"
```

**Windows (PowerShell):**

```powershell
pip install "token-smithers[learning] @ git+https://github.com/shacharbard/token-smithers.git@stable"
```

That's it. The `token-smithers` command is now available globally.

<details>
<summary>Alternative: clone and install</summary>

```bash
git clone https://github.com/shacharbard/token-smithers.git
cd token-smithers
pip install ".[learning]"
```

</details>

<details>
<summary>Optional extras</summary>

| Extra | What it adds |
|-------|-------------|
| `learning` | Cross-session learning, semantic cache (aiosqlite) — **recommended** |
| `prose` | Prose/documentation summarization via TextRank (sumy) |
| Both | `pip install "token-smithers[learning,prose] @ git+https://github.com/shacharbard/token-smithers.git@stable"` |

**Core dependencies** (always installed): `mcp>=1.0.0`, `pyyaml>=6.0`, `pydantic>=2.0`

</details>

<details>
<summary>For contributors</summary>

```bash
git clone https://github.com/shacharbard/token-smithers.git
cd token-smithers
pip install -e ".[dev]"
```

</details>

## Quick Start

Three commands to get running:

```bash
pip install "token-smithers[learning] @ git+https://github.com/shacharbard/token-smithers.git@stable"
token-smithers setup                      # Pick which MCP servers to compress
# ... use your AI coding tool normally ...
token-smithers stats                      # Check your savings
```

### Automatic setup

The setup command finds your existing MCP servers and lets you choose which ones to compress.

```bash
token-smithers setup
```

```
Found 2 MCP config files:

  Global (~/.claude.json): 3 servers
    1. github        npx -y @modelcontextprotocol/server-github
    2. slack         npx -y @anthropic/server-slack
    3. memory        npx -y @modelcontextprotocol/server-memory

  Project (.mcp.json): 2 servers
    4. filesystem    npx -y @modelcontextprotocol/server-filesystem .
    5. my-database   my-db-server --port 5432

Which servers should token-smithers compress? (comma-separated, or 'all')
> 1,4,5
```

That's it. Token Smithers:
- Creates a config file per server in `~/.token-smithers/configs/`
- Updates your MCP configs to route through Token Smithers
- Backs up originals to `.mcp.json.backup` / `~/.claude.json.backup`

The setup scans both config locations:
- **Project-level:** `.mcp.json` in the current directory
- **User-level:** `~/.claude.json` (global servers available in all projects)

### Undo setup

To remove Token Smithers and restore your original MCP server connections:

```bash
token-smithers setup --undo
```

```
Unwrapping 3 servers:
  github        → restored to: npx -y @modelcontextprotocol/server-github
  filesystem    → restored to: npx -y @modelcontextprotocol/server-filesystem .
  my-database   → restored to: my-db-server --port 5432

Updated:
  ~/.claude.json — 1 server restored
  .mcp.json      — 2 servers restored
```

This reads the generated YAML configs to recover the original commands and rewrites your MCP configs back to direct connections. Your backup files are preserved.

### Check your savings

```bash
token-smithers stats
```

```
  "Excellent..."

  === Token Smithers — Session Stats ===
  Events:     142
  Original:   284,000 tokens
  Compressed: 156,200 tokens
  Saved:      127,800 tokens (45.0%)

  Smithers, we saved 127,800 tokens. Not a single one squandered.

  === Per-Strategy Breakdown ===
  Strategy                        Count   Original Compressed
  ------------------------------ ------ ---------- ----------
  whitespace_normalizer              142     284000     241400
  toon_compressor                     38     120000      54000
  yaml_transcoder                     67      98000      73500
  smart_truncation                    12      42000      28700
```

### Status line

See live token savings in your terminal status bar:

```bash
token-smithers status-line
```

```
Smithers: 1.2M (42%) | today: 52.0K (38%)     # green when >= 40%
Smithers: 340.5K (23%) | today: 12.1K (19%)   # blue when >= 20%
Smithers: 8.2K (6%) | today: 1.4K (5%)        # red when < 20%
```

Shows cumulative all-time savings and today's savings side by side. Data is read from the SQLite learning store, so it persists across sessions.

**Claude Code** — add to your settings (`~/.claude/settings.json`):

```json
{
  "statusLine": "token-smithers status-line"
}
```

**Terminal prompt** — add to your `.zshrc` or `.bashrc`:

```bash
# Show Smithers savings in your prompt
export PS1='$(token-smithers status-line) \$ '
```

**tmux status bar:**

```bash
set -g status-right '#(token-smithers status-line)'
```

The status line updates automatically as the metrics file is written during your session.

## Manual Setup

If you prefer to configure Token Smithers by hand instead of using `token-smithers setup`, here's how.

### Step 1: Create a config file

For each MCP server you want to compress, create a YAML config file:

```yaml
# ~/.token-smithers/configs/filesystem.yaml
backend:
  command: "npx"
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
```

That's the minimum. All compression features are enabled by default with sensible settings. See [Configuration](#configuration) for the full reference.

### Step 2: Update your MCP config

Edit your `.mcp.json` (project) or `~/.claude.json` (global) to route through Token Smithers.

**Before** (direct connection):
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

**After** (through Token Smithers):
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "token-smithers",
      "args": ["--config", "~/.token-smithers/configs/filesystem.yaml"]
    }
  }
}
```

Token Smithers works with **any MCP server** — filesystem, GitHub, database, custom servers, anything that speaks the MCP protocol. Wrap each backend server you want compressed with its own config file.

**Multiple servers:**
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "token-smithers",
      "args": ["--config", "~/.token-smithers/configs/filesystem.yaml"]
    },
    "github": {
      "command": "token-smithers",
      "args": ["--config", "~/.token-smithers/configs/github.yaml"]
    }
  }
}
```

### Manual undo

To remove Token Smithers manually, edit your MCP config and replace the Token Smithers entries with the original commands. The original commands are stored in each YAML config file under `backend.command` and `backend.args`:

```bash
# Check what the original command was
cat ~/.token-smithers/configs/filesystem.yaml
```

```yaml
backend:
  command: "npx"
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

Then update your `.mcp.json` or `~/.claude.json` to use that command directly instead of `Token Smithers`.

## Configuration

All settings have sensible defaults. You only need to configure `backend.command` to get started.

### Full config reference

```yaml
# Backend MCP server to proxy
backend:
  command: "npx"                    # Command to start the backend server
  args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
  env: {}                           # Extra environment variables

# Tool filtering (passthrough by default)
filter:
  mode: "passthrough"               # passthrough | allowlist | blocklist
  tools: []                         # Tool names to allow/block
  patterns: []                      # Regex patterns to match tool names

# Compression pipeline
compression:
  enabled: true
  size_gate_threshold: 2000         # Skip compression for results under this token count
  adapters:                         # Ordered list — first match wins
    - name: whitespace_normalizer   # Always-on cleanup
    - name: null_field_elider
    - name: path_prefix_deduplicator
    - name: timestamp_normalizer
    - name: log_level_filter        # Off by default
      enabled: false
    - name: error_stack_compressor
      enabled: false
    - name: code_comment_stripper
      enabled: false
    - name: sentence_scorer         # Requires 'prose' extra
      enabled: false
    - name: rle_encoder
    - name: toon_compressor         # JSON arrays -> columnar format
    - name: yaml_transcoder         # Non-tabular JSON -> YAML
    - name: file_redirect           # Oversized results -> temp file
      enabled: false
    - name: smart_truncation        # Safety net (always last)

# Schema virtualization (DietMCP-style)
schema_virtualization:
  enabled: false                    # Enable to compress tool schemas
  tier: 2                           # 1=lossless, 2=brief descriptions, 3=one-liner notation
  frequent_call_threshold: 3        # Tools called >= N times stay at Tier 1

# Semantic result caching
semantic_cache:
  enabled: false                    # Enable for similarity-based result caching
  similarity_threshold: 0.85        # 0.0-1.0, higher = stricter matching
  max_entries: 1000
  ttl_seconds: 86400                # Cache entry lifetime (null = no expiry)

# Cross-session learning
learning:
  enabled: true                     # SQLite persistence for usage stats + caching
  db_path: "~/.token-smithers/learning.db"

# Dashboard / metrics
dashboard:
  enabled: true
  metrics_file_path: "~/.token-smithers/metrics.json"

# System prompt optimization
system_prompt:
  enabled: true
  compress_instructions: true       # Compress backend server instructions at startup

# Statistical reranker
reranker:
  enabled: true                     # Reorder tools/list by usage frequency
  max_tools: 500
  recency_weight: 0.3

# Caching
cache:
  schema_cache_ttl: 3600            # Tools/list cache TTL (seconds)
  call_cache_max: 200               # Max exact-match cached results
  diff_store_max: 100               # Max semantic diff entries

# Observability
observability:
  metrics_to_stderr: true           # Emit [Token Smithers] log lines per compression event
  log_level: "INFO"
```

### Adapter Pipeline

Compression adapters run in order. Each adapter decides if it can handle the content (`can_handle`), and if so, compresses it. Results pass through the full pipeline.

| Adapter | What it does | Default |
|---------|-------------|---------|
| `whitespace_normalizer` | Collapses whitespace, normalizes line endings | On |
| `null_field_elider` | Removes null/empty fields from JSON | On |
| `path_prefix_deduplicator` | Deduplicates repeated path prefixes | On |
| `timestamp_normalizer` | Normalizes verbose timestamps | On |
| `log_level_filter` | Collapses verbose logs to ERROR/WARN with counts | Off |
| `error_stack_compressor` | Deduplicates stack frames, extracts root cause | Off |
| `code_comment_stripper` | Removes inline comments and docstrings | Off |
| `sentence_scorer` | Extracts important sentences (TextRank, requires `prose` extra) | Off |
| `rle_encoder` | Compacts repeated consecutive values | On |
| `toon_compressor` | Converts uniform JSON arrays to columnar format (40-60% savings) | On |
| `yaml_transcoder` | Converts non-tabular JSON to YAML (15-25% savings) | On |
| `key_aliasing` | Replaces long repeated JSON keys with short aliases | On |
| `ast_skeleton` | Extracts Python function signatures, drops bodies | On |
| `graph_encoder` | Compacts dependency graphs to adjacency notation | On |
| `progressive_disclosure` | Returns summary + file pointer for oversized results | On |
| `file_redirect` | Writes oversized results to temp file, returns pointer | Off |
| `smart_truncation` | Head+tail truncation as safety net (always last) | On |

## Architecture

```
src/token_sieve/
  domain/          # Pure Python domain core (zero external deps)
    model.py       #   ContentEnvelope, CompressionEvent, value objects
    ports.py       #   CompressionStrategy, DeduplicationStrategy protocols
    pipeline.py    #   CompressionPipeline service
    ports_cache.py #   SemanticCachePort protocol
    ports_learning.py # LearningStore protocol
    ports_schema.py   # SchemaVirtualizerPort protocol
    metrics.py     #   InMemoryMetricsCollector
  adapters/        # Implementations (external deps allowed)
    compression/   #   17 compression strategy adapters
    cache/         #   Call cache, semantic cache, invalidation, schema cache
    backend/       #   MCP client transport + connector
    learning/      #   SQLite learning store
    schema/        #   Schema virtualizer (DietMCP notation)
    rerank/        #   Statistical reranker + persistence
    dedup/         #   Window-based deduplication
  server/          # MCP proxy server
    proxy.py       #   ProxyServer (MCP handlers, dependency wiring)
    metrics_sink.py #  Stderr metrics formatter
    metrics_writer.py # Periodic JSON metrics file writer
    tool_filter.py #   Allowlist/blocklist tool filtering
  config/          # YAML config loading + Pydantic validation
  cli/             # CLI entry point (proxy, pipe, stats modes)
```

Hexagonal Architecture (Ports & Adapters) with DDD principles. The domain core has zero external dependencies — all I/O goes through Protocol interfaces.

## Usage Examples

### Proxy a filesystem server

```yaml
# Token Smithers.yaml
backend:
  command: "npx"
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
```

### Proxy with aggressive compression

```yaml
backend:
  command: "npx"
  args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

compression:
  adapters:
    - name: whitespace_normalizer
    - name: null_field_elider
    - name: path_prefix_deduplicator
    - name: timestamp_normalizer
    - name: log_level_filter
      enabled: true                  # Enable log filtering
    - name: code_comment_stripper
      enabled: true                  # Strip code comments
    - name: sentence_scorer
      enabled: true                  # Requires 'prose' extra
    - name: rle_encoder
    - name: toon_compressor
    - name: yaml_transcoder
    - name: smart_truncation

schema_virtualization:
  enabled: true
  tier: 3                            # DietMCP one-liner notation

semantic_cache:
  enabled: true                      # Cache similar read results
  similarity_threshold: 0.90         # Strict matching
```

### Filter tools

```yaml
backend:
  command: "my-mcp-server"

filter:
  mode: "blocklist"
  tools: ["dangerous_tool"]
  patterns: ["^internal_.*"]          # Regex: block tools starting with "internal_"
```

### Pipe mode (standalone compression)

```bash
# Compress a file directly (no MCP server needed)
cat large-output.json | token-smithers --pipe

# Compress from file
token-smithers --pipe input.txt
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov

# Run integration tests only
pytest -m integration

# Run benchmarks
pytest -m benchmark
```

### Test stats

- 950+ tests
- 91.8% coverage
- Unit / Integration / E2E / Contract / Golden file test pyramid

## Security

Token Smithers runs locally on your machine. It never sends data to external services.

| Measure | Detail |
|---------|--------|
| **Config parsing** | `yaml.safe_load` only — no code execution via YAML |
| **SQL queries** | Parameterized throughout — no SQL injection |
| **Temp files** | Created with `0o600` permissions — owner-only access |
| **Cache safety** | Semantic cache restricted to read-only tools via allowlist — mutating tools never cached |
| **Fault isolation** | Learning store fails open — I/O errors don't crash tool calls |
| **No eval/exec** | All compression is pure string/JSON manipulation |
| **Dependency audit** | 0 vulnerabilities in direct dependencies (mcp, pyyaml, pydantic, aiosqlite) |
| **Static analysis** | bandit: 0 medium/high findings on 5,235 lines of code |

See [SECURITY.md](SECURITY.md) for the full trust model, vulnerability reporting, and audit details.

```bash
# Run security checks yourself
pip install bandit pip-audit
bandit -r src/token_sieve/ -ll    # Static analysis
pip-audit                          # Dependency vulnerabilities
```

## Acknowledgements

Token Smithers was inspired by and builds on ideas from:

- **[DietMCP](https://github.com/austindixson/dietmcp)** — Pioneered the DietMCP one-liner notation (`tool(param, ?opt) desc`) for schema compression and type elision. Token Smithers' Tier 3 schema virtualization implements this notation with frequency-aware tier selection.
- **[AnythingLLM](https://github.com/Mintplex-Labs/anything-llm)** ([toolReranker.js](https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/agents/aibitat/utils/toolReranker.js)) — Inspired the statistical tool reranking approach. Token Smithers adapts this concept for MCP proxy-level reranking with cross-session persistence via SQLite.

## License

MIT
