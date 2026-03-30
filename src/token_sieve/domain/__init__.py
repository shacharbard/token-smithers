"""Domain core: value objects, entities, Protocol interfaces, and services.

Public API exports for the token-sieve domain layer.
"""

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import (
    CompressedResult,
    CompressionEvent,
    ContentEnvelope,
    ContentType,
    TokenBudget,
)
from token_sieve.domain.pipeline import CompressionPipeline

__all__ = [
    "CharEstimateCounter",
    "CompressedResult",
    "CompressionEvent",
    "CompressionPipeline",
    "ContentEnvelope",
    "ContentType",
    "TokenBudget",
]
