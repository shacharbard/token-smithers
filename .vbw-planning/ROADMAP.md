# token-sieve Roadmap

**Goal:** token-sieve

**Scope:** 4 phases

## Progress
| Phase | Status | Plans | Tasks | Commits |
|-------|--------|-------|-------|---------|
| 01 | ○ Planned |
| 2 | Pending | 0 | 0 | 0 |
| 3 | Pending | 0 | 0 | 0 |
| 4 | Pending | 0 | 0 | 0 |

---

## Phase List
- [ ] [Phase 1: Domain Core](#phase-1-domain-core)
- [ ] [Phase 2: MCP Proxy + Free Adapters](#phase-2-mcp-proxy-free-adapters)
- [ ] [Phase 3: Premium Adapters + Learning](#phase-3-premium-adapters-learning)
- [ ] [Phase 4: Intelligence + Dashboard](#phase-4-intelligence-dashboard)

---

## Phase 1: Domain Core

**Goal:** Define domain interfaces (CompressionStrategy, BackendToolAdapter, DeduplicationStrategy), value objects (TokenBudget, CompressedResult), entities (ToolResult, SessionContext), and the CompressionPipeline service. Include CLI test harness for verification. Pure Python, zero dependencies.

**Requirements:** Result compression, Session deduplication, Budget-aware throttling, Plugin architecture

**Success Criteria:**
- All domain interfaces defined with Protocol classes
- CompressionPipeline passes unit tests with mock strategies
- CLI harness can pipe text through pipeline and report token savings
- 100% unit test coverage on domain core
- Zero external dependencies in core module

**Dependencies:** None

---

## Phase 2: MCP Proxy + Free Adapters

**Goal:** Wrap domain core as an MCP server using mcp2py. Implement free adapters (PassthroughAdapter, TruncationCompressor, basic dedup). Working proxy that Claude Code can connect to.

**Requirements:** Schema virtualization, Result compression, Plugin architecture

**Success Criteria:**
- MCP server starts and responds to tool calls
- Passthrough adapter forwards results unchanged
- TruncationCompressor reduces results by configurable ratio
- Basic dedup detects identical consecutive tool results
- Integration tests verify MCP round-trip

**Dependencies:** Phase 1

---

## Phase 3: Premium Adapters + Learning

**Goal:** Add premium compression adapters (jCodeMunch, jDocMunch, LLMLingua-2, RTK). Add attention-aware routing and semantic diff returns. Adapters are swappable via config.

**Requirements:** Result compression, Attention-aware routing, Semantic diff returns, Plugin architecture

**Success Criteria:**
- Each adapter passes CompressionStrategy contract tests
- Attention tracker records which results get referenced
- Semantic diff returns only changed content on re-reads
- Config file controls which adapters are active
- Contract tests run against all adapters uniformly

**Dependencies:** Phase 2

---

## Phase 4: Intelligence + Dashboard

**Goal:** Schema virtualization (meta-tools replace raw schemas), budget-aware progressive compression, token accounting dashboard, self-tuning compression ratios based on attention data.

**Requirements:** Schema virtualization, Budget-aware throttling, Token accounting dashboard

**Success Criteria:**
- Meta-tool discovery reduces schema tokens by 80%+
- Compression aggressiveness scales with context fill level
- Dashboard exposes real-time savings per technique
- System auto-tunes compression ratios from attention data
- End-to-end test shows 40-60% total token reduction

**Dependencies:** Phase 3

