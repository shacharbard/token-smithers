# Token-Saving System: Research Report

> Date: 2026-03-30
> Current stack: jCodeMunch, jDocMunch, context-mode, MuninnDB-lite

---

## Current Stack — Gap Analysis

| Layer | Tool | What It Saves | Remaining Gap |
|-------|------|---------------|---------------|
| Code reads | jCodeMunch | 85-95% per file read | Sliced edits via `get_file_content(start_line, end_line)` cover most cases; gap only for whole-file restructuring |
| Doc reads | jDocMunch | 90-97% per doc access | Large sections can't be subdivided further |
| Command output | context-mode | Up to 98% on large outputs | Outputs between 1-5KB slip through unfiltered |
| Long-term memory | MuninnDB-lite | Avoids re-discovery across sessions | 36 tools = significant schema overhead |
| **Tool schemas** | **Nothing** | — | **5,000-10,000 tokens every turn** |
| **System prompt bloat** | **Nothing** | — | **8,000-15,000 tokens of CLAUDE.md + instructions** |
| **CLI output formatting** | **Nothing** | — | **Boilerplate, noise, test summaries** |
| **Conversation history** | **Nothing** | — | **Grows linearly; compaction loses 60-70%** |
| **Redundant tool calls** | **Nothing** | — | **Re-reads, duplicate greps, repeated git status** |
| **Structural waste** | **Nothing** | — | **Unused skill frontmatter, duplicate configs** |

**Key insight:** The stack excels at **read-time compression** (getting less data IN). The biggest untouched areas are: (1) **schema overhead** — tool definitions repeated every turn, (2) **output-side compression** for medium-sized results that don't trigger context-mode's 5KB threshold, and (3) **conversation history management** — the compounding cost of keeping old turns.

---

## The 5 Untapped Token-Saving Layers

### Layer 1: CLI Output Compression (RTK)

**The problem:** Even with context-mode, raw CLI output from git, test runners, linters, and build tools contains massive boilerplate.

**The solution:** [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk) — a Rust CLI proxy that intercepts shell commands and compresses output before it reaches the LLM.

- **60-90% reduction** on 100+ commands (git, pytest, cargo, npm, docker, etc.)
- Single binary, zero dependencies, <10ms overhead
- Auto-hooks into Claude Code transparently via shell rewriting
- Works **alongside** context-mode — RTK compresses first, context-mode filters if still large
- Also available as [MCP server (rtk-mcp)](https://github.com/ousamabenyounes/rtk-mcp)

**Estimated savings:** 80% on CLI outputs. In a 30-min session: ~118K tokens → ~24K tokens.

### Layer 2: Structural Waste Detection (Token Optimizer)

**The problem:** "Ghost tokens" — invisible overhead from unused skills, duplicate configs between CLAUDE.md and MEMORY.md, bloated MCP definitions, redundant system reminders.

**The solution:** [Token Optimizer](https://github.com/alexgreensh/token-optimizer) — audits your entire setup and identifies structural waste.

Key capabilities:
- **Per-component audit** of CLAUDE.md, MEMORY.md, skills, MCP servers, commands, rules
- **Quality scoring** with 7 signals (context fill, stale reads, bloated results, compaction depth, duplicates, etc.)
- **Read-cache**: detects and blocks redundant file reads (8-30% savings)
- **Tool result archive**: stores outputs >4KB to disk, retrievable post-compaction without re-running
- **Smart compaction checkpoints** at 50%, 65%, 80% fill — restores richest checkpoint post-compaction
- Tracks quality degradation: "Opus 4.6 drops from 93% to 76% across a 1M context window"

**Estimated savings:** 10-30% structural overhead reduction + better compaction survival.

### Layer 3: Dynamic Tool Schema Loading

**The problem:** MCP servers (jCodeMunch ~6 tools, jDocMunch ~6 tools, context-mode ~5 tools, MuninnDB ~36 tools) inject **all** their schemas into every request. That's potentially 10,000+ tokens of tool definitions repeated on every single turn.

**Solutions:**

1. **MCP Protocol-level fix (coming):** [SEP-1576](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576) proposes schema deduplication via JSON `$ref`, adaptive field control, and embedding-based tool filtering. Real-world measurement: 27,462 tokens consumed by 137 tools across 11 MCP servers before conversation even starts.

2. **Speakeasy Dynamic Toolsets** — provides "meta" tools that let the LLM discover only the tools it needs per task. Up to [160x token reduction](https://www.speakeasy.com/blog/how-we-reduced-token-usage-by-100x-dynamic-toolsets-v2) on tool schemas while maintaining 100% task success.

3. **Claude Code's ToolSearch** already does deferred loading for built-in tools (46.9% reduction), but MCP server tools are NOT deferred. A **custom MCP gateway/proxy** that serves tool schemas on-demand rather than all-at-once would be the equivalent for your MCP stack.

**Key insight:** MuninnDB-lite's 36 tools are likely the single biggest schema overhead contributor. Consider whether all 36 need to be loaded, or if a gateway could expose a "discover" + "execute" meta-tool pattern instead.

### Layer 4: Prompt/Context Compression Middleware

**The problem:** Even after all tools do their work, tool results, conversation history, and system prompts still contain compressible content — filler words, redundant syntax, low-information tokens.

**Solutions (from academic research):**

| Tool | Approach | Compression | Speed | Best For |
|------|----------|-------------|-------|----------|
| [LLMLingua-2](https://github.com/microsoft/LLMLingua) | BERT classifier removes low-info tokens | 2-20x | Fast (3-6x faster than v1) | Verbose tool results, docs |
| [Selective Context](https://github.com/liyucheng09/Selective_Context) | Self-information entropy filtering | 40-60% retained | Very fast | First-pass on large reads |
| [RECOMP](https://github.com/carriex/recomp) | Query-conditioned extractive/abstractive | 5-10x | Medium | RAG-style tool results |

**The middleware idea:** An MCP server that wraps other tool results through LLMLingua-2 before they enter context:

```
Agent → Tool Call → MCP Server → [raw result] → LLMLingua-2 → [compressed result] → Agent
```

This catches everything that slips through jCodeMunch/jDocMunch/context-mode — medium-sized outputs (1-5KB), JSON API responses, error logs, etc.

### Layer 5: Conversation History Management (Dynamic Context Pruning)

**The problem:** Conversation history grows linearly. Compaction loses 60-70% of context. Old tool results sit in history consuming tokens long after they're relevant.

**Solutions:**

1. [**OpenCode Dynamic Context Pruning (DCP)**](https://github.com/Opencode-DCP/opencode-dynamic-context-pruning) — replaces pruned content with placeholders before sending to LLM, without modifying actual session history. Features:
   - Range and message-level compression
   - Deduplication of identical tool calls
   - Auto-purge of errored tool outputs after N turns
   - Protected content (subagents, skills) survives pruning
   - Model-directed: the LLM decides what to compress and when

2. **Budget-aware progressive compression** (custom build): An MCP server that tracks context fill level and becomes progressively more aggressive:
   - 0-50% fill: full detail
   - 50-70%: summarize tool results older than 5 turns
   - 70-85%: aggressive compression, signatures only
   - 85%+: trigger compaction with checkpoint preservation

---

## Complementary Repos — Complete Discovery List

### HIGH Priority (Fill direct gaps in current stack)

| Repo | What It Does | Gap It Fills | Savings |
|------|-------------|--------------|---------|
| [rtk-ai/rtk](https://github.com/rtk-ai/rtk) | Rust CLI proxy, compresses 100+ commands | CLI output noise | 60-90% |
| [alexgreensh/token-optimizer](https://github.com/alexgreensh/token-optimizer) | Structural waste audit + quality tracking | Ghost tokens, compaction | 10-30% |
| [Opencode-DCP](https://github.com/Opencode-DCP/opencode-dynamic-context-pruning) | Dynamic context pruning plugin | Conversation history bloat | 20-40% |
| [microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | BERT-based prompt compression | Medium output compression | 2-20x |

### MEDIUM Priority (Architectural improvements)

| Repo | What It Does | Gap It Fills | Savings |
|------|-------------|--------------|---------|
| [ooples/token-optimizer-mcp](https://github.com/ooples/token-optimizer-mcp) | MCP server with caching + Brotli compression | Redundant tool results | 95%+ cache hits |
| [ousamabenyounes/rtk-mcp](https://github.com/ousamabenyounes/rtk-mcp) | RTK as MCP server | CLI output (MCP route) | 60-90% |
| [microsoft/mcp-gateway](https://github.com/microsoft/mcp-gateway) | MCP reverse proxy + lifecycle management | Schema aggregation | Variable |
| [zilliztech/GPTCache](https://github.com/zilliztech/GPTCache) | Semantic caching for LLM calls | Repeated similar queries | High on cache hits |
| [angrysky56/ast-mcp-server](https://github.com/angrysky56/ast-mcp-server) | Semantic graph + AST code understanding | Deep dependency navigation | Medium |

### REFERENCE (Ideas to adapt, not plug-and-play)

| Repo | Why It Matters |
|------|----------------|
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | Proxy architecture reference with caching and cost tracking |
| [Speakeasy Dynamic Toolsets](https://www.speakeasy.com/docs/mcp/build/toolsets/dynamic-toolsets) | Pattern for on-demand tool schema loading |
| [SEP-1576](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576) | MCP protocol-level schema deduplication proposal |
| [paul-gauthier/aider](https://github.com/paul-gauthier/aider) | Repo-map concept (compressed AST codebase summary) |

---

## Creative New Approach: The Compression Gateway

The biggest untapped opportunity is **a single MCP gateway that sits between Claude Code and all other MCP servers**:

```
Claude Code <-> Compression Gateway <-> [jCodeMunch, jDocMunch, context-mode, MuninnDB, etc.]
```

This gateway would:

1. **Schema virtualization** — expose only 3-5 meta-tools (`discover_tools`, `call_tool`, `search_tools`) instead of 50+ individual schemas. The LLM describes what it wants; the gateway routes to the right backend tool. Saves 5,000-10,000 tokens/turn.

2. **Result compression** — run LLMLingua-2 on any tool result >1KB before returning it. Catches the 1-5KB gap that context-mode misses.

3. **Session-level dedup** — hash tool results and replace repeated content with backreferences ("Same as file_a.py lines 1-20 read 3 turns ago").

4. **Budget-aware throttling** — query context fill level and progressively compress as session grows.

5. **Result archival** — store full tool results on disk, return compressed versions to context, allow `expand <id>` retrieval post-compaction.

**Estimated additional savings:** 40-60% on top of current stack.

---

## Recommended Implementation Priority

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Install [RTK](https://github.com/rtk-ai/rtk) (`brew install rtk`) | 5 min | Immediate 60-90% CLI savings |
| 2 | Install [Token Optimizer](https://github.com/alexgreensh/token-optimizer) and audit setup | 30 min | Find and fix ghost tokens |
| 3 | Install [DCP](https://github.com/Opencode-DCP/opencode-dynamic-context-pruning) for conversation pruning | 30 min | 20-40% history savings |
| 4 | Reduce MuninnDB tool exposure (disable unused tools or build meta-tool wrapper) | 2-4 hrs | Thousands of tokens/turn |
| 5 | Build LLMLingua-2 MCP compression proxy for medium-sized outputs | 1-2 days | 2-5x on 1-5KB results |
| 6 | Build full compression gateway with schema virtualization | 1-2 weeks | 40-60% additional savings |

---

## Token Waste Quantitative Estimates

| Source | Tokens per occurrence | Frequency | Session waste |
|--------|----------------------|-----------|---------------|
| Tool schemas in prompt | 5,000-10,000 | Every turn (20-50) | 100K-500K |
| Full file reads (unnecessary) | 1,000-5,000 | 5-15 per session | 5K-75K |
| Verbose command output | 500-10,000 | 5-10 per session | 2.5K-100K |
| Redundant reads/greps | 500-3,000 | 3-10 per session | 1.5K-30K |
| Result metadata/wrappers | 50-200 | 30-80 calls | 1.5K-16K |
| **Total estimated waste** | | | **110K-720K tokens/session** |

## Academic References

| Paper | Key Finding |
|-------|-------------|
| LLMLingua (EMNLP 2023) | 20x compression with minimal loss using perplexity-based token pruning |
| LLMLingua-2 (ACL 2024) | 3-6x faster via trained BERT classifier, task-agnostic |
| LongLLMLingua (2024) | Question-aware compression outperforms question-agnostic for long context |
| RECOMP (ICLR 2024) | Extractive + abstractive compression for retrieved documents |
| Selective Context (2023) | Self-information filtering at phrase level preserves more coherence |
| In-context Autoencoder (2024) | 4x compression via "memory tokens" (requires fine-tuning) |

---

## Additional Repos: mcp2py & mcp2cli

### mcp2py — MCP Server → Python Module Bridge

**Repo:** [MaximeRivest/mcp2py](https://github.com/MaximeRivest/mcp2py)

**What it does:** Transforms any MCP server into native Python functions. `load("npx server-xyz")` → call `server.tool_name()` directly from Python. Supports stdio and HTTP/SSE transports, auto-generates type hints and `.pyi` stubs, handles OAuth automatically.

**Key capabilities:**
- Tools → Python methods with type hints and docstrings
- Resources → Python attributes
- Prompts → callable template functions
- Sampling/elicitation hooks for request/response customization
- Async subprocess management for MCP servers

**Fit for token-sieve:**
- **HIGH** — Ideal foundation for the compression gateway's client layer. Instead of writing raw MCP JSON-RPC, use `load()` to connect to backend MCP servers (jCodeMunch, jDocMunch, context-mode, MuninnDB) and call their tools as Python functions.
- **HIGH** — Sampling/elicitation hooks provide interception points for injecting compression logic.
- **MEDIUM** — Not middleware itself, but a building block. The gateway uses mcp2py to talk to backends, then exposes compressed results through its own MCP interface.

**Verdict:** Use as the **client layer** of the compression gateway — handles all MCP protocol plumbing so we focus on compression logic.

### mcp2cli — MCP/OpenAPI/GraphQL → CLI Generator

**Repo:** [knowsuchagency/mcp2cli](https://github.com/knowsuchagency/mcp2cli)

**What it does:** Converts MCP servers, OpenAPI specs, and GraphQL endpoints into CLI commands at runtime. Claims **96-99% token savings** on tool schemas by not exposing raw schemas to the LLM.

**Key capabilities:**
- Multi-protocol: MCP (stdio + HTTP/SSE), OpenAPI (JSON/YAML), GraphQL
- **TOON encoding** — token-efficient output format designed for LLMs
- Tool filtering (include/exclude patterns, HTTP method filters)
- "Bake mode" — saves connection settings as named tools for repeated use
- Spec/tool caching with configurable TTL
- jq filtering and result truncation (`--head`)

**Fit for token-sieve:**
- **HIGH** — TOON encoding is directly relevant as an output compression format to study/adapt.
- **HIGH** — Tool filtering pattern addresses schema bloat — expose only needed tools per task.
- **MEDIUM** — "Bake mode" aligns with schema virtualization concept.
- **LOW as middleware** — CLI generator, not an interceptor. Can't sit between Claude Code and MCP servers transparently.

**Verdict:** TOON encoding and tool filtering patterns worth studying/adapting. The tool itself is better for direct CLI usage than as a gateway component.

### Architecture Integration

```
Claude Code
    ↓
token-sieve (compression gateway MCP server)    ← WE BUILD THIS
    ↓ uses mcp2py to call backend servers
    ├── jCodeMunch (via mcp2py.load())
    ├── jDocMunch (via mcp2py.load())
    ├── context-mode (via mcp2py.load())
    └── MuninnDB (via mcp2py.load())
```

- **mcp2py** = plumbing connecting the gateway to backend MCP servers
- **mcp2cli's TOON encoding** = pattern to adapt for compressing tool results
