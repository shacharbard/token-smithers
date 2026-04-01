"""Schema virtualization engine -- three-tier tool schema compression.

Compresses MCP tool schemas across three tiers:
- Tier 1: Lossless cleanup (remove boilerplate)
- Tier 2: Description compression (shorten verbose descriptions)
- Tier 3: DietMCP notation (compact one-liner for simple tools)

Satisfies SchemaVirtualizerPort protocol structurally.
"""

from __future__ import annotations

import copy
import re
from typing import Any


class SchemaVirtualizer:
    """Three-tier schema virtualization engine.

    Stores original schemas for on-demand retrieval via get_full_schema().
    Frequency-aware: frequently-called tools can be forced to lower tiers.
    """

    def __init__(self, frequent_threshold: int = 5) -> None:
        self._originals: dict[str, dict] = {}
        self._frequent_threshold = frequent_threshold

    def virtualize(
        self,
        tools: list[dict],
        *,
        tier: int = 3,
        usage_stats: dict[str, int] | None = None,
    ) -> list[dict]:
        """Compress tool schemas at the specified tier level.

        Args:
            tools: List of MCP tool dicts with 'name', 'description', 'inputSchema'.
            tier: Maximum compression tier (1=lossless, 2=descriptions, 3=DietMCP).
            usage_stats: Optional tool_name -> call_count for frequency-aware selection.

        Returns:
            List of tools with compressed schemas (new dicts, originals untouched).
        """
        usage_stats = usage_stats or {}
        result: list[dict] = []

        for tool in tools:
            # Store a deep copy of the original
            tool_name = tool.get("name", "")
            self._originals[tool_name] = copy.deepcopy(tool)

            # Determine effective tier for this tool
            effective_tier = self._effective_tier(tool_name, tier, usage_stats)

            # Work on a deep copy
            compressed = copy.deepcopy(tool)

            # Tier 1: Lossless cleanup (always applied)
            if effective_tier >= 1:
                compressed = self._apply_tier1(compressed)

            # Tier 2: Description compression
            if effective_tier >= 2:
                compressed = self._apply_tier2(compressed)

            # Tier 3: DietMCP notation
            if effective_tier >= 3:
                compressed = self._apply_tier3(compressed)

            result.append(compressed)

        return result

    def get_full_schema(self, tool_name: str) -> dict | None:
        """Retrieve the original uncompressed schema for a tool."""
        return self._originals.get(tool_name)

    # --- Tier 1: Lossless cleanup ---

    def _apply_tier1(self, tool: dict) -> dict:
        """Remove boilerplate without losing semantic content."""
        schema = tool.get("inputSchema", {})
        tool["inputSchema"] = self._cleanup_schema(schema, tool.get("name", ""))
        return tool

    def _cleanup_schema(self, schema: dict, tool_name: str = "") -> dict:
        """Tier 1 lossless cleanup on a schema dict."""
        # Remove $schema
        schema.pop("$schema", None)

        # Remove additionalProperties: false (redundant for MCP)
        if schema.get("additionalProperties") is False:
            del schema["additionalProperties"]

        # Strip title if it matches the tool name
        if schema.get("title") == tool_name:
            del schema["title"]

        # Clean up properties
        props = schema.get("properties", {})
        for prop_name, prop_def in props.items():
            if isinstance(prop_def, dict):
                self._cleanup_property(prop_def)

        return schema

    def _cleanup_property(self, prop: dict) -> None:
        """Clean a single property definition in-place."""
        # Remove empty descriptions
        if prop.get("description") == "":
            del prop["description"]

        # Flatten single-item oneOf/anyOf
        for key in ("oneOf", "anyOf"):
            items = prop.get(key)
            if isinstance(items, list) and len(items) == 1:
                single = items[0]
                del prop[key]
                prop.update(single)

        # Recurse into nested properties
        nested_props = prop.get("properties", {})
        for nested_def in nested_props.values():
            if isinstance(nested_def, dict):
                self._cleanup_property(nested_def)

        # Recurse into items (arrays) -- only if items has its own structure
        items_def = prop.get("items")
        if isinstance(items_def, dict) and (
            "properties" in items_def or "items" in items_def or "oneOf" in items_def or "anyOf" in items_def or "description" in items_def
        ):
            self._cleanup_property(items_def)

    # --- Tier 2: Description compression ---

    # Patterns that indicate example text to strip
    _EXAMPLE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(?:^|\.\s+)[^.]*\bExample:\s*[^.]*\.?", re.IGNORECASE),
        re.compile(r"(?:^|\.\s+)[^.]*\be\.g\.\s*[^.]*\.?", re.IGNORECASE),
    ]

    # Max words for a compressed description
    _MAX_DESCRIPTION_WORDS: int = 50

    def _apply_tier2(self, tool: dict) -> dict:
        """Compress verbose descriptions and strip examples."""
        # Compress tool-level description
        if desc := tool.get("description", ""):
            tool["description"] = self._compress_description(desc)

        # Compress property-level descriptions
        schema = tool.get("inputSchema", {})
        self._compress_property_descriptions(schema)

        return tool

    def _compress_description(self, text: str) -> str:
        """Shorten a description: strip examples, truncate to first N sentences."""
        if not text:
            return text

        # Strip example sentences
        cleaned = self._strip_examples(text)

        # If already short enough, return as-is
        words = cleaned.split()
        if len(words) <= self._MAX_DESCRIPTION_WORDS:
            return cleaned.strip()

        # Keep first 2 sentences or MAX_DESCRIPTION_WORDS words
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        result_sentences: list[str] = []
        word_count = 0
        for sent in sentences:
            sent_words = sent.split()
            if word_count + len(sent_words) > self._MAX_DESCRIPTION_WORDS and result_sentences:
                break
            result_sentences.append(sent)
            word_count += len(sent_words)
            if len(result_sentences) >= 2:
                break

        return " ".join(result_sentences).strip()

    def _strip_examples(self, text: str) -> str:
        """Remove sentences containing Example: or e.g. patterns."""
        # Split into sentences and filter
        sentences = re.split(r"(?<=[.!?])\s+", text)
        filtered: list[str] = []
        for sent in sentences:
            if re.search(r"\bExample:", sent, re.IGNORECASE):
                continue
            if re.search(r"\be\.g\.", sent, re.IGNORECASE):
                continue
            filtered.append(sent)
        result = " ".join(filtered)
        return result if result else text  # fallback to original if all stripped

    def _compress_property_descriptions(self, schema: dict) -> None:
        """Recursively compress descriptions within property definitions."""
        props = schema.get("properties", {})
        for prop_def in props.values():
            if not isinstance(prop_def, dict):
                continue
            if desc := prop_def.get("description", ""):
                compressed = self._compress_description(desc)
                if compressed:
                    prop_def["description"] = compressed
                else:
                    del prop_def["description"]
            # Recurse into nested objects
            if "properties" in prop_def:
                self._compress_property_descriptions(prop_def)
            items_def = prop_def.get("items")
            if isinstance(items_def, dict) and "properties" in items_def:
                self._compress_property_descriptions(items_def)

    # --- Tier 3: DietMCP notation (placeholder for Task 4) ---

    def _apply_tier3(self, tool: dict) -> dict:
        """Convert simple tools to DietMCP notation. Implemented in Task 4."""
        return tool

    def _effective_tier(
        self, tool_name: str, requested_tier: int, usage_stats: dict[str, int]
    ) -> int:
        """Determine effective tier based on frequency data."""
        call_count = usage_stats.get(tool_name, 0)
        if call_count >= self._frequent_threshold:
            return 1  # Frequently-called tools stay at Tier 1 (full schema)
        return requested_tier
