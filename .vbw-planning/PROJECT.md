# token-sieve

MCP compression gateway that reduces token usage by intercepting and compressing tool results between Claude Code and backend MCP servers. Uses Hexagonal Architecture (Ports & Adapters) with DDD principles for a clean, testable, plug-and-play system.

**Core value:** Transparent token savings through a plugin-based compression gateway — users choose their own compression adapters (free or premium) without touching core logic.

## Requirements

### Validated
- Plugin architecture with Protocol-based interfaces
- Hexagonal / Ports & Adapters architecture
- Pure Python domain core with zero external dependencies
- TDD-first development (RED → GREEN → REFACTOR)

### Active
- [ ] Schema virtualization (meta-tools instead of raw schemas)
- [ ] Result compression (LLMLingua-2, truncation, extractive)
- [ ] Session deduplication (hash-based backreferences)
- [ ] Budget-aware throttling (progressive compression as context fills)
- [ ] Attention-aware routing (learn which results matter, compress noise)
- [ ] Semantic diff returns (only return what changed since last read)
- [ ] Token accounting dashboard (real-time savings metrics)
- [ ] Plug-and-play adapters (swap compression strategies via config)

### Out of Scope
- Modifying Claude Code internals
- Fine-tuning or training models
- Cloud/SaaS deployment (local-first)

## Constraints
- **Pure Python core**: Domain logic has zero external dependencies
- **Python 3.11+**: Modern Python with Protocol support
- **MCP compatible**: Must work as standard MCP server
- **mcp2py**: Used as client layer for backend MCP server communication

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hexagonal Architecture | Plugin support + testability + DDD alignment | Clean ports/adapters separation |
| Pure Onion phasing | Domain-first build order enables TDD from Phase 1 | 4 phases: Core → Proxy → Adapters → Intelligence |
| mcp2py for backend comms | Handles MCP protocol plumbing, lets us focus on compression | Client layer dependency |
| Contract tests for adapters | Every adapter must pass same interface tests | Uniform quality across free/premium adapters |
