"""Tests for TreeSitterASTExtractor.

RED phase: contract tests + per-language behavioral tests for the
tree-sitter based multi-language AST skeleton extractor.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Test data -- realistic multi-function code snippets (~30-50 lines each)
# ---------------------------------------------------------------------------

_PYTHON_CODE = '''\
import os
from typing import List, Optional


class DataProcessor:
    """Process and transform data records."""

    def __init__(self, source: str, batch_size: int = 100) -> None:
        """Initialize the processor with a data source."""
        self._source = source
        self._batch_size = batch_size
        self._records: List[dict] = []

    @staticmethod
    def validate(record: dict) -> bool:
        """Check that a record has required fields."""
        required = {"id", "name", "value"}
        if not isinstance(record, dict):
            return False
        return required.issubset(record.keys())

    def process(self, records: List[dict]) -> List[dict]:
        """Filter and transform a batch of records."""
        valid = [r for r in records if self.validate(r)]
        transformed = []
        for rec in valid:
            rec["value"] = rec["value"] * 2
            rec["processed"] = True
            transformed.append(rec)
        self._records.extend(transformed)
        return transformed


def summarize(data: List[dict], key: str = "value") -> Optional[float]:
    """Compute the average of a numeric field across records."""
    values = [r[key] for r in data if key in r]
    if not values:
        return None
    return sum(values) / len(values)
'''

_TYPESCRIPT_CODE = '''\
import { EventEmitter } from "events";

/**
 * Configuration options for the cache.
 */
interface CacheOptions {
    maxSize: number;
    ttlMs: number;
    onEvict?: (key: string) => void;
}

/**
 * Generic LRU cache with TTL support.
 */
class LRUCache<K, V> extends EventEmitter {
    private store: Map<K, { value: V; expiresAt: number }>;
    private readonly maxSize: number;
    private readonly ttlMs: number;

    constructor(options: CacheOptions) {
        super();
        this.store = new Map();
        this.maxSize = options.maxSize;
        this.ttlMs = options.ttlMs;
    }

    /**
     * Retrieve a value by key, returning undefined if expired.
     */
    get(key: K): V | undefined {
        const entry = this.store.get(key);
        if (!entry) return undefined;
        if (Date.now() > entry.expiresAt) {
            this.store.delete(key);
            return undefined;
        }
        return entry.value;
    }

    /**
     * Insert or update a cache entry.
     */
    set(key: K, value: V): void {
        if (this.store.size >= this.maxSize) {
            const oldest = this.store.keys().next().value;
            this.store.delete(oldest);
            this.emit("evict", oldest);
        }
        this.store.set(key, {
            value,
            expiresAt: Date.now() + this.ttlMs,
        });
    }
}

export function createCache<K, V>(opts: CacheOptions): LRUCache<K, V> {
    return new LRUCache<K, V>(opts);
}
'''

_JAVASCRIPT_CODE = '''\
const EventEmitter = require("events");

/**
 * Rate limiter using sliding window algorithm.
 */
class RateLimiter extends EventEmitter {
    constructor(maxRequests, windowMs) {
        super();
        this.maxRequests = maxRequests;
        this.windowMs = windowMs;
        this.windows = new Map();
    }

    /**
     * Check whether the given key is allowed to proceed.
     */
    isAllowed(key) {
        const now = Date.now();
        const requests = this.windows.get(key) || [];
        const valid = requests.filter((t) => now - t < this.windowMs);
        if (valid.length >= this.maxRequests) {
            this.emit("limited", key);
            return false;
        }
        valid.push(now);
        this.windows.set(key, valid);
        return true;
    }

    /**
     * Reset the counter for a specific key.
     */
    reset(key) {
        this.windows.delete(key);
        this.emit("reset", key);
    }
}

const createLimiter = (max, windowMs) => {
    return new RateLimiter(max, windowMs);
};

module.exports = { RateLimiter, createLimiter };
'''

_GO_CODE = '''\
package cache

import (
\t"sync"
\t"time"
)

// Item represents a cache entry with expiration.
type Item struct {
\tValue     interface{}
\tExpiresAt time.Time
}

// Cache is a thread-safe in-memory key-value store.
type Cache struct {
\tmu    sync.RWMutex
\titems map[string]Item
\tttl   time.Duration
}

// NewCache creates a Cache with the given TTL.
func NewCache(ttl time.Duration) *Cache {
\treturn &Cache{
\t\titems: make(map[string]Item),
\t\tttl:   ttl,
\t}
}

// Get retrieves a value, returning false if missing or expired.
func (c *Cache) Get(key string) (interface{}, bool) {
\tc.mu.RLock()
\tdefer c.mu.RUnlock()
\titem, ok := c.items[key]
\tif !ok || time.Now().After(item.ExpiresAt) {
\t\treturn nil, false
\t}
\treturn item.Value, true
}

// Set inserts or updates a cache entry.
func (c *Cache) Set(key string, value interface{}) {
\tc.mu.Lock()
\tdefer c.mu.Unlock()
\tc.items[key] = Item{
\t\tValue:     value,
\t\tExpiresAt: time.Now().Add(c.ttl),
\t}
}

// Delete removes an entry from the cache.
func (c *Cache) Delete(key string) {
\tc.mu.Lock()
\tdefer c.mu.Unlock()
\tdelete(c.items, key)
}
'''

_RUST_CODE = '''\
use std::collections::HashMap;
use std::time::{Duration, Instant};

/// A cache entry holding a value and its expiration time.
struct CacheEntry<V> {
    value: V,
    expires_at: Instant,
}

/// Thread-safe TTL cache.
pub struct TtlCache<V> {
    entries: HashMap<String, CacheEntry<V>>,
    ttl: Duration,
}

impl<V: Clone> TtlCache<V> {
    /// Create a new cache with the given TTL.
    pub fn new(ttl: Duration) -> Self {
        TtlCache {
            entries: HashMap::new(),
            ttl,
        }
    }

    /// Retrieve a value if it exists and has not expired.
    pub fn get(&self, key: &str) -> Option<V> {
        self.entries.get(key).and_then(|entry| {
            if Instant::now() < entry.expires_at {
                Some(entry.value.clone())
            } else {
                None
            }
        })
    }

    /// Insert or update a cache entry.
    pub fn set(&mut self, key: String, value: V) {
        self.entries.insert(
            key,
            CacheEntry {
                value,
                expires_at: Instant::now() + self.ttl,
            },
        );
    }

    /// Remove an entry from the cache.
    pub fn remove(&mut self, key: &str) -> Option<V> {
        self.entries.remove(key).map(|e| e.value)
    }
}

/// Create a cache with a default 60-second TTL.
pub fn default_cache<V: Clone>() -> TtlCache<V> {
    TtlCache::new(Duration::from_secs(60))
}
'''

_JAVA_CODE = '''\
package com.example.cache;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Simple thread-safe cache with TTL support.
 *
 * @param <V> the type of cached values
 */
public class SimpleCache<V> {

    private final Map<String, CacheEntry<V>> store;
    private final long ttlMillis;

    /**
     * Create a cache with the specified TTL in milliseconds.
     *
     * @param ttlMillis time-to-live for cache entries
     */
    public SimpleCache(long ttlMillis) {
        this.store = new ConcurrentHashMap<>();
        this.ttlMillis = ttlMillis;
    }

    /**
     * Retrieve a cached value, or null if absent or expired.
     */
    public V get(String key) {
        CacheEntry<V> entry = store.get(key);
        if (entry == null) {
            return null;
        }
        if (System.currentTimeMillis() > entry.expiresAt) {
            store.remove(key);
            return null;
        }
        return entry.value;
    }

    /**
     * Insert or update a cache entry.
     */
    public void put(String key, V value) {
        long expiresAt = System.currentTimeMillis() + ttlMillis;
        store.put(key, new CacheEntry<>(value, expiresAt));
    }

    @Override
    public String toString() {
        return "SimpleCache{size=" + store.size() + ", ttl=" + ttlMillis + "}";
    }

    private static class CacheEntry<V> {
        final V value;
        final long expiresAt;

        CacheEntry(V value, long expiresAt) {
            this.value = value;
            this.expiresAt = expiresAt;
        }
    }
}
'''

_NON_CODE = """\
The quick brown fox jumps over the lazy dog. This is a paragraph of plain
English text that does not contain any programming constructs. It discusses
the weather, which has been quite pleasant lately. The temperature is around
72 degrees Fahrenheit with a light breeze from the northwest. Tomorrow's
forecast calls for partly cloudy skies with a chance of afternoon showers.
We should plan accordingly and bring an umbrella just in case. Overall,
it has been a mild spring with moderate rainfall and comfortable temperatures.
"""

_MALFORMED_CODE = """\
def broken(
    @@@ syntax error here !!!
    class {{{[[[
    fn totally_wrong ->->-> {{
    public void <<<>>>
    func ((())) +++
    let === !!! @@@
    def another_broken(:
    @@@ more garbage $$$
    {{{ ]]] >>>
"""


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestTreeSitterASTContract(CompressionStrategyContract):
    """TreeSitterASTExtractor must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        return TreeSitterASTExtractor()


# ---------------------------------------------------------------------------
# Specific behavioral tests -- P01: Python + TypeScript + basics
# ---------------------------------------------------------------------------


class TestTreeSitterASTSpecific:
    """TreeSitterASTExtractor-specific behavioral tests."""

    def test_can_handle_true_for_python(self):
        """Python source with classes and functions triggers can_handle."""
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_CODE, content_type=ContentType.CODE
        )
        strategy = TreeSitterASTExtractor()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_true_for_typescript(self):
        """TypeScript source triggers can_handle."""
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_TYPESCRIPT_CODE, content_type=ContentType.CODE
        )
        strategy = TreeSitterASTExtractor()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_for_non_code(self):
        """Plain English text should not trigger can_handle."""
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_NON_CODE, content_type=ContentType.TEXT
        )
        strategy = TreeSitterASTExtractor()
        assert strategy.can_handle(envelope) is False

    def test_can_handle_false_when_tree_sitter_unavailable(self):
        """When tree-sitter is not installed, can_handle returns False."""
        from token_sieve.adapters.compression import tree_sitter_ast
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_CODE, content_type=ContentType.CODE
        )
        strategy = TreeSitterASTExtractor()

        with patch.object(tree_sitter_ast, "_TREE_SITTER_AVAILABLE", False):
            assert strategy.can_handle(envelope) is False

    def test_compress_python_skeleton(self):
        """Python skeleton keeps signatures + docstrings, drops bodies."""
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_CODE, content_type=ContentType.CODE
        )
        strategy = TreeSitterASTExtractor()
        result = strategy.compress(envelope)

        # Class and method signatures present
        assert "class DataProcessor" in result.content
        assert "def __init__" in result.content
        assert "def validate" in result.content
        assert "def process" in result.content
        assert "def summarize" in result.content
        # Docstrings preserved
        assert "Process and transform data records" in result.content
        assert "Initialize the processor" in result.content
        # Bodies dropped
        assert "self._records.extend" not in result.content
        assert "rec[\"value\"] = rec[\"value\"] * 2" not in result.content
        # Decorator preserved
        assert "@staticmethod" in result.content
        # Marker present
        assert "[token-sieve:" in result.content

    def test_compress_typescript_skeleton(self):
        """TypeScript skeleton keeps signatures + JSDoc, drops bodies."""
        from token_sieve.adapters.compression.tree_sitter_ast import (
            TreeSitterASTExtractor,
        )

        envelope = ContentEnvelope(
            content=_TYPESCRIPT_CODE, content_type=ContentType.CODE
        )
        strategy = TreeSitterASTExtractor()
        result = strategy.compress(envelope)

        # Interface preserved
        assert "interface CacheOptions" in result.content
        # Class signature
        assert "class LRUCache" in result.content
        # Method signatures
        assert "get(key" in result.content
        assert "set(key" in result.content
        # JSDoc preserved
        assert "Generic LRU cache with TTL support" in result.content
        assert "Retrieve a value by key" in result.content
        # Bodies dropped
        assert "this.store.delete" not in result.content
        assert "Date.now()" not in result.content
        # Marker present
        assert "[token-sieve:" in result.content
