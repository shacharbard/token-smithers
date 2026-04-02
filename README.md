# Token Smithers

*"Your context window is a fortune. Stop squandering it."*

```
Claude Code  <-->  Token Smithers (proxy)  <-->  Backend MCP Server
```

Your loyal assistant for token efficiency. Token Smithers sits between Claude Code and your backend MCP servers, transparently compressing tool schemas and results to reduce token usage. No changes to Claude Code or your backend servers required.

Like any good assistant, Smithers does the dirty work silently — and reports back with style.

**Works with any MCP client** — Claude Code, Codex, Cursor, Windsurf, Cline, or anything that speaks the MCP protocol. Not tied to any specific tool.

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

## Performance Overhead

Token Smithers adds negligible latency. The compression pipeline is pure Python string and JSON operations — no ML inference, no GPU, no network calls.

**Measured pipeline latency (full 11-adapter chain):**

| Content type | Input size | Pipeline time | Compression |
|-------------|-----------|--------------|-------------|
| Small JSON object | 29 chars | 0.06ms | 28% smaller |
| JSON array (50 items) | 5.7 KB | 0.23ms | 47% smaller |
| JSON array (200 items) | 31 KB | 0.99ms | 58% smaller |
| Python source file | 2.8 KB | 0.37ms | 58% smaller |
| Dependency graph | 162 chars | 0.13ms | 2% smaller |

A typical MCP tool call (filesystem read, API request, database query) takes **50-500ms** for the backend to respond. Token Smithers's compression pipeline runs in **under 1ms** even for large results — adding less than 1% to the total round-trip time.

**Why so fast:**
- All compression is string manipulation, regex, and JSON parse/serialize — no heavy computation
- Content-aware routing skips adapters that can't handle the content type (`can_handle` check)
- Small results (<2000 tokens) skip the pipeline entirely via the size gate
- No network calls — everything runs in-process between Claude Code and your backend

The only non-trivial cost is the semantic cache fuzzy lookup (SequenceMatcher on up to 100 cached entries), which adds 1-5ms when enabled. Exact-match cache hits are O(1).

## Requirements

- **Python 3.11+**
- **A backend MCP server** — any MCP-compatible server that Token Smithers will proxy to (e.g., filesystem, GitHub, database, or custom servers)

## Installation

**Recommended** — install with `pipx` (isolated, no venv needed):

```bash
pipx install token-smithers[learning]
```

Or with `pip`:

```bash
pip install token-smithers[learning]
```

That's it. The `token-smithers` command is now available globally.

The `learning` extra includes cross-session learning and semantic caching. For the full feature set:

```bash
# Recommended: all features
pipx install "Token Smithers[learning,prose]"
```

<details>
<summary>Optional extras explained</summary>

| Extra | What it adds | Install command |
|-------|-------------|----------------|
| `learning` | Cross-session learning, semantic cache (aiosqlite) | `pip install token-smithers[learning]` |
| `prose` | Prose/documentation summarization via TextRank (sumy) | `pip install token-smithers[prose]` |
| Both | All features | `pip install "Token Smithers[learning,prose]"` |

**Core dependencies** (always installed):

| Package | Purpose |
|---------|---------|
| `mcp>=1.0.0` | MCP protocol (server + client) |
| `pyyaml>=6.0` | Config file parsing |
| `pydantic>=2.0` | Config validation |

</details>

<details>
<summary>Install from source (for contributors)</summary>

```bash
git clone https://github.com/shacharbard/token-smithers.git
cd token-smithers
pip install -e ".[dev]"
```

</details>

## Quick Start

Three commands to get running:

```bash
pipx install token-smithers[learning]    # 1. Install
token-smithers setup                      # 2. Pick which MCP servers to compress
# ... use Claude Code normally ...
token-smithers stats                      # 3. Check your savings
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

- 933+ tests
- 91.8% coverage
- Unit / Integration / E2E / Contract / Golden file test pyramid

## License

MIT
