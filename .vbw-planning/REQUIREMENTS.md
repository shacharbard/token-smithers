# token-sieve Requirements

Defined: 2026-03-30 | Core value: Transparent token savings through plugin-based compression gateway

## v1 Requirements

### Core Compression
- [ ] **REQ-01**: CompressionStrategy Protocol — interface for all compression adapters
- [ ] **REQ-02**: CompressionPipeline — chains multiple strategies, respects token budgets
- [ ] **REQ-03**: TokenBudget value object — tracks remaining budget, compression targets
- [ ] **REQ-04**: ToolResult entity — wraps tool outputs with metadata (size, type, source)

### Deduplication
- [ ] **REQ-05**: DeduplicationStrategy Protocol — interface for dedup approaches
- [ ] **REQ-06**: Hash-based dedup — detect identical tool results, return backreferences
- [ ] **REQ-07**: Semantic diff — on re-read, return only what changed since last access

### MCP Integration
- [ ] **REQ-08**: MCP server exposing compression gateway to Claude Code
- [ ] **REQ-09**: BackendToolAdapter Protocol — interface for calling backend MCP servers
- [ ] **REQ-10**: mcp2py-based adapter for connecting to backend MCP servers

### Plugin System
- [ ] **REQ-11**: Config-driven adapter selection (YAML/JSON config file)
- [ ] **REQ-12**: Free adapters: PassthroughAdapter, TruncationCompressor
- [ ] **REQ-13**: Premium adapters: jCodeMunch, jDocMunch, LLMLingua-2, RTK

### Intelligence
- [ ] **REQ-14**: Attention-aware routing — track which results LLM references, compress noise
- [ ] **REQ-15**: Budget-aware throttling — progressive compression as context fills
- [ ] **REQ-16**: Schema virtualization — meta-tools replace 50+ raw tool schemas

### Observability
- [ ] **REQ-17**: Token accounting dashboard — per-technique savings, real-time metrics
- [ ] **REQ-18**: Metrics exposed as MCP resource for agent self-optimization

## v2 Requirements
- [ ] **REQ-19**: Speculative prefetch — predict next tool calls, pre-cache results
- [ ] **REQ-20**: TOON encoding support (from mcp2cli patterns)
- [ ] **REQ-21**: Multi-session learning — persist attention data across sessions

## Out of Scope

- Model fine-tuning or training (complexity, not aligned with plugin approach)
- Cloud deployment or SaaS features (local-first tool)
- Modifying Claude Code source code (we work through MCP protocol only)
