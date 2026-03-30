"""CLI entry point for token-sieve compression pipeline.

Reads text from stdin or a file argument, pipes it through the
CompressionPipeline, and reports token savings to stderr.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.domain.ports import CompressionStrategy, TokenCounter


class CharEstimateCounter:
    """Zero-dependency token counter: ~chars/4 estimate (~75% accurate)."""

    def count(self, text: str) -> int:
        """Estimate token count as character count divided by 4."""
        return max(1, len(text) // 4)


class PassthroughStrategy:
    """Phase 1 default strategy: passes content through unchanged."""

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Always handles any envelope."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Return the envelope unchanged."""
        return envelope


def create_pipeline() -> tuple[CompressionPipeline, CharEstimateCounter]:
    """Create a pipeline with CharEstimateCounter and PassthroughStrategy."""
    counter = CharEstimateCounter()
    pipeline = CompressionPipeline(counter=counter)
    pipeline.register(ContentType.TEXT, PassthroughStrategy())
    return pipeline, counter


def run(
    input_text: str,
    pipeline: CompressionPipeline,
    counter: TokenCounter,
) -> tuple[str, dict[str, object]]:
    """Process text through the pipeline, return (output, stats).

    Stats dict contains: original_tokens, compressed_tokens, savings_ratio.
    """
    envelope = ContentEnvelope(content=input_text, content_type=ContentType.TEXT)
    original_tokens = counter.count(input_text)

    result_envelope, events = pipeline.process(envelope)
    compressed_tokens = counter.count(result_envelope.content)

    savings_ratio = (
        0.0
        if original_tokens == 0
        else 1.0 - (compressed_tokens / original_tokens)
    )

    stats = {
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "savings_ratio": savings_ratio,
    }
    return result_envelope.content, stats


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, read input, run pipeline, print results.

    Output goes to stdout, savings report to stderr.
    Returns 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(
        prog="token-sieve",
        description="Compress text to reduce token usage",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Input file path (reads from stdin if omitted)",
    )
    args = parser.parse_args(argv)

    # Read input
    input_text: str = ""
    if args.file is not None:
        try:
            with open(args.file, encoding="utf-8") as f:
                input_text = f.read()
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        input_text = sys.stdin.read()

    if not input_text.strip():
        print(
            "Error: no input provided. Usage: echo 'text' | token-sieve",
            file=sys.stderr,
        )
        return 1

    # Run pipeline
    pipeline, counter = create_pipeline()
    output, stats = run(input_text, pipeline, counter)

    # Output compressed text to stdout
    print(output, end="")

    # Report savings to stderr
    original = stats["original_tokens"]
    compressed = stats["compressed_tokens"]
    ratio = stats["savings_ratio"]
    print(
        f"Original: {original} tokens | "
        f"Compressed: {compressed} tokens | "
        f"Savings: {ratio:.1%}",
        file=sys.stderr,
    )

    return 0
