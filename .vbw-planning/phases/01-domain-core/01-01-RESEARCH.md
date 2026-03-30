---
phase: "01-domain-core"
title: "Domain Core Research"
type: research
confidence: high
date: 2026-03-30
---

## Findings

### 1. Python Protocol Classes — Best Practices

**Structural subtyping (duck typing) without inheritance:**
- `typing.Protocol` (Python 3.8+, stable in 3.12+) enables structural subtyping: a class satisfies a Protocol if it implements the required members — no explicit `class Foo(MyProtocol)` needed. This is ideal for the token-sieve ports because adapters never need to import domain interfaces.
- Compose narrow Protocols via multiple inheritance (`class TaggedReadableResource(SupportsClose, SupportsRead, Protocol): ...`). Keep each Protocol to 1–3 methods so structural checks stay meaningful.
- Prefer `@property` over bare mutable attributes in Protocols to avoid invariance errors: `content: object` on a Protocol causes type errors if an implementor declares `content: int`. A `@property` returning the base type sidesteps this.

**Runtime checkability — use sparingly:**
- `@runtime_checkable` adds `isinstance()` support, but only checks member *existence*, not signatures or return types. A class with `def close(self, force: bool) -> int` still passes a Protocol requiring `def close(self) -> None`.
- `isinstance()` against a `@runtime_checkable` Protocol that includes data attributes will *evaluate* properties as a side effect (CPython issue #102433). Avoid using `@runtime_checkable` on Protocols with data attributes unless the attribute check is intentional.
- For performance-sensitive dispatch prefer `hasattr()` over `isinstance()` against runtime-checkable Protocols; the latter is measurably slower.
- Recommended pattern for token-sieve: mark top-level port Protocols `@runtime_checkable` only where dynamic dispatch is needed (e.g., `CompressionStrategy` selector at pipeline entry). Leave `SessionRepository`, `MetricsCollector`, `TokenCounter` as plain Protocols for static checking only.

**Abstract methods on explicit subclasses:**
- Omitting the body (or writing `...`) on a Protocol method makes it implicitly abstract: explicit subclasses that do not implement it cannot be instantiated. This enforces the contract at class creation time, which pairs well with pytest contract tests.

```python
from typing import Protocol, runtime_checkable

class CompressionStrategy(Protocol):
    def can_handle(self, envelope: "ContentEnvelope") -> bool: ...
    def compress(self, envelope: "ContentEnvelope") -> "ContentEnvelope": ...

@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
```

---

### 2. Python Project Structure — Hexagonal Architecture

**Canonical src-layout for a pure-Python domain core:**
```
token_sieve/
  src/
    token_sieve/
      domain/           # pure Python, zero external deps
        model.py        # ContentEnvelope, CompressionEvent, ContentType
        pipeline.py     # CompressionPipeline
        ports.py        # Protocol interfaces: CompressionStrategy, SessionRepository,
                        #                     MetricsCollector, TokenCounter
        session.py      # InMemorySessionRepo (Phase 1 in-process adapter)
      adapters/         # external-dep adapters (Phase 2+)
        __init__.py
      cli/              # primary adapter / entrypoint
        __init__.py
        main.py
  tests/
    unit/
      domain/
    integration/
  pyproject.toml
```

**Key structural rules:**
- `domain/` imports *nothing* outside stdlib. No `pydantic`, no `click`, no `httpx`. The domain test suite proves this by running with no third-party packages installed.
- `ports.py` lives *inside* `domain/` (not a separate `ports/` folder) for Phase 1 — it only contains Protocol definitions. This follows the principle that ports are part of the domain vocabulary; adapters are outside.
- The CLI lives in `adapters/cli/` or a top-level `cli/` module; it imports from `domain/` but the domain never imports from CLI.
- `session.py` in `domain/` is acceptable for Phase 1's `InMemorySessionRepo` since it has no external deps. Move it to `adapters/` in Phase 2 when a persistent repo is introduced.

**Dependency rule summary:** `domain` ← `adapters` ← `cli`. Arrows point outward. The domain is the innermost hexagon and knows nothing about what wraps it.

---

### 3. pytest Structure for Protocol-Based DDD Projects

**Contract test pattern — base class fixture:**
The canonical approach for Protocol-based DDD is an abstract base test class that defines the contract. Concrete adapter tests inherit it and inject their implementation. This gives you "works like a Strategy" guarantees for every adapter.

```python
# tests/unit/domain/test_compression_strategy_contract.py
import pytest
from token_sieve.domain.ports import CompressionStrategy

class CompressionStrategyContract:
    """Base contract every CompressionStrategy implementation must satisfy."""

    @pytest.fixture
    def strategy(self) -> CompressionStrategy:
        raise NotImplementedError

    def test_can_handle_returns_bool(self, strategy):
        from token_sieve.domain.model import ContentEnvelope, ContentType
        env = ContentEnvelope(content="hello", content_type=ContentType.TEXT)
        result = strategy.can_handle(env)
        assert isinstance(result, bool)

    def test_compress_returns_envelope(self, strategy):
        from token_sieve.domain.model import ContentEnvelope, ContentType
        env = ContentEnvelope(content="hello world " * 50, content_type=ContentType.TEXT)
        result = strategy.compress(env)
        assert isinstance(result, ContentEnvelope)

# tests/unit/domain/test_truncate_strategy.py
from .test_compression_strategy_contract import CompressionStrategyContract
from token_sieve.domain.strategies import TruncateStrategy

class TestTruncateStrategy(CompressionStrategyContract):
    @pytest.fixture
    def strategy(self):
        return TruncateStrategy(max_chars=100)
```

**Factory-as-fixture for value objects:**
Use factory fixtures (returning a callable) when the same value object needs to be constructed with varied inputs across multiple tests:

```python
@pytest.fixture
def make_envelope():
    def _factory(content="test", content_type=ContentType.TEXT):
        return ContentEnvelope(content=content, content_type=content_type)
    return _factory
```

**conftest.py structure:**
- `tests/conftest.py` — session-scoped shared fixtures (pipeline instance, mock strategy)
- `tests/unit/domain/conftest.py` — domain-specific factories
- Keep `scope="function"` (default) for all mutable domain objects; use `scope="session"` only for truly immutable singletons

**Coverage enforcement:**
Add `[tool.pytest.ini_options]` to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--cov=token_sieve.domain --cov-fail-under=100 --cov-branch"
testpaths = ["tests"]
```

---

### 4. Content-Routed Pipeline Pattern in Python

**Pattern: Router + Chain-of-Responsibility per content type:**
The canonical Python approach is a dict-based router that maps `ContentType → list[CompressionStrategy]`, then iterates the chain. This avoids `if/elif` chains and makes strategy registration O(1) lookup.

```python
from dataclasses import dataclass, field
from typing import Protocol
from token_sieve.domain.model import ContentEnvelope, ContentType

class CompressionStrategy(Protocol):
    def can_handle(self, envelope: ContentEnvelope) -> bool: ...
    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope: ...

@dataclass
class CompressionPipeline:
    _routes: dict[ContentType, list[CompressionStrategy]] = field(default_factory=dict)

    def register(self, content_type: ContentType, strategy: CompressionStrategy) -> None:
        self._routes.setdefault(content_type, []).append(strategy)

    def process(self, envelope: ContentEnvelope) -> ContentEnvelope:
        chain = self._routes.get(envelope.content_type, [])
        for strategy in chain:
            if strategy.can_handle(envelope):
                envelope = strategy.compress(envelope)
        return envelope
```

**Key design decisions:**
- Each strategy in a chain receives the *output* of the previous one (pipeline semantics), not a copy of the original. This allows chained strategies to build on each other's work (e.g., truncate then deduplicate).
- The `can_handle` guard lets strategies opt out mid-chain (e.g., skip if content is already short enough). This avoids needing a separate router per threshold.
- A fallback `ContentType.UNKNOWN` route can hold a pass-through strategy for unrecognized content.
- For Phase 1, the pipeline is a plain dataclass with no registration framework — strategies are added via `pipeline.register(...)` in CLI setup code.

---

### 5. Frozen Dataclasses as Value Objects in Python DDD

**Core pattern:**
`@dataclass(frozen=True)` is the idiomatic Python 3.11+ choice for value objects. It provides:
- Immutability enforced by `__setattr__`/`__delattr__` raising `FrozenInstanceError`
- Auto-generated `__eq__` based on all fields (value semantics by definition)
- Auto-generated `__hash__` (required since `frozen=True` implies equality is defined)

```python
from dataclasses import dataclass
from enum import Enum, auto

class ContentType(Enum):
    TEXT = auto()
    JSON = auto()
    CODE = auto()
    UNKNOWN = auto()

@dataclass(frozen=True)
class ContentEnvelope:
    content: str
    content_type: ContentType
    metadata: dict = field(default_factory=dict)  # NOTE: mutable default breaks hashability

    def __post_init__(self):
        if not isinstance(self.content, str):
            raise TypeError(f"content must be str, got {type(self.content)}")
        if len(self.content) == 0:
            raise ValueError("content must not be empty")
```

**Immutability caveat with mutable fields:**
`frozen=True` prevents rebinding fields but does *not* deep-freeze mutable values. A `dict` or `list` field on a frozen dataclass is still mutable in place. Solutions:
- Use `tuple` instead of `list` for collections.
- Use `types.MappingProxyType` for dict-like metadata.
- Or convert to `frozenset` in `__post_init__` via `object.__setattr__(self, 'tags', frozenset(tags))`.

**Transformations return new instances:**
Because value objects are immutable, "mutation" operations must return a new instance. Use `dataclasses.replace()`:
```python
from dataclasses import replace

compressed = replace(envelope, content=compressed_content)
```

**CompressionEvent as an event value object:**
```python
@dataclass(frozen=True)
class CompressionEvent:
    original_tokens: int
    compressed_tokens: int
    strategy_name: str
    content_type: ContentType

    @property
    def savings_ratio(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return 1.0 - (self.compressed_tokens / self.original_tokens)
```

**Avoid `slots=True` complexity for Phase 1:** `@dataclass(frozen=True, slots=True)` (Python 3.10+) adds memory efficiency but complicates inheritance. For Phase 1 value objects with no inheritance, it is safe to add; skip it to keep the implementation minimal.

---

## Relevant Patterns

- **Ports as Protocol classes inside `domain/`** — avoids the common mistake of putting ports in a separate package that then creates circular import pressure.
- **Contract test base class** — the `CompressionStrategyContract` base class pattern lets Phase 2 adapter tests inherit all behavioral guarantees automatically. Write it once in Phase 1 even if only mock strategies exist.
- **`dataclasses.replace()`** for pipeline transformations — the pipeline's `process()` method passes the envelope through a chain; each strategy returns `replace(envelope, content=...)` rather than mutating, making the data flow traceable and testable.
- **`dict[ContentType, list[Strategy]]` router** — simpler than a visitor or observer pattern for the routing problem; the `ContentType` enum is the key, eliminating string-based dispatch.

---

## Risks

- **`@runtime_checkable` + data attributes**: If `ContentEnvelope` is used as a Protocol attribute and `isinstance()` is called, property getters may fire unexpectedly. Mitigate: only mark method-only Protocols as `@runtime_checkable`.
- **Mutable defaults in frozen dataclasses**: `metadata: dict = field(default_factory=dict)` on a `frozen=True` dataclass still produces a mutable dict — hash consistency is violated if the dict is mutated after construction. Mitigate: use `MappingProxyType` or forbid mutable fields entirely on value objects.
- **100% coverage on domain core with Protocol-only files**: Coverage tools may not count Protocol method stubs as covered. Mitigate: add a smoke test that imports and inspects Protocol members, or exclude Protocol-only files from strict branch coverage.
- **Strategy chain ordering**: If multiple strategies all return `can_handle=True`, chain order matters for output quality. Phase 1 should enforce registration order determinism via a list (not a set).

---

## Recommendations

1. **Use plain `Protocol` (no `@runtime_checkable`) for all ports except `TokenCounter`**, which may need dynamic dispatch to select between `CharEstimateCounter` and a real tokenizer. Mark only `TokenCounter` with `@runtime_checkable`.

2. **Place all domain interfaces in a single `domain/ports.py`** rather than split files. Phase 1 has 4–5 Protocols; splitting adds navigation overhead with no benefit. Refactor to separate files in Phase 2 if the count exceeds ~10.

3. **Write the `CompressionStrategyContract` base class in Phase 1** even though only mock strategies exist. This creates a template that Phase 2 real-strategy authors must follow, preventing behavioral drift.

4. **`@dataclass(frozen=True)` for all value objects; use `dataclasses.replace()` everywhere**. Do not add `slots=True` in Phase 1 — it adds complexity and is not needed for correctness or performance at this scale.

5. **Enforce zero-dependency domain in CI** by adding a test that imports `token_sieve.domain` inside a subprocess with a stripped `sys.path` (only stdlib) and asserts it does not raise `ImportError`. This prevents accidental external-dep leakage into the core.

6. **Structure the pipeline `process()` method to return a `(ContentEnvelope, list[CompressionEvent])` tuple** rather than side-effecting into a collector, making the pipeline pure and trivial to unit-test without mock injection.
