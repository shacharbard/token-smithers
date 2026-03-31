"""CLI entry point for token-sieve.

Two modes:
- **Proxy mode** (default): Start MCP proxy server that Claude Code connects to.
- **Pipe mode** (--pipe): Read stdin, compress, write stdout. Backward compat.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.domain.ports import TokenCounter

from token_sieve.adapters.compression.passthrough import PassthroughStrategy


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
    Uses pipeline events for token counts when available to avoid
    double-counting.
    """
    envelope = ContentEnvelope(content=input_text, content_type=ContentType.TEXT)
    result_envelope, events = pipeline.process(envelope)

    if events:
        original_tokens = events[0].original_tokens
        compressed_tokens = events[-1].compressed_tokens
    else:
        original_tokens = counter.count(input_text)
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


def _run_pipe(args: argparse.Namespace) -> int:
    """Pipe mode: read input, compress, write output."""
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
            "Error: no input provided. Usage: echo 'text' | token-sieve --pipe",
            file=sys.stderr,
        )
        return 1

    pipeline, counter = create_pipeline()
    output, stats = run(input_text, pipeline, counter)

    print(output, end="")

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


async def _run_proxy(config_path: str | None = None) -> int:
    """Proxy mode: start MCP server."""
    from token_sieve.server.proxy import ProxyServer

    if config_path is not None:
        from token_sieve.config.schema import load_config

        path = Path(config_path)
        config = load_config(path)
    else:
        from token_sieve.config.schema import TokenSieveConfig

        config = TokenSieveConfig()

    proxy = ProxyServer.create_from_config(config)
    await proxy.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, dispatch to proxy or pipe mode.

    Returns 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(
        prog="token-sieve",
        description="MCP compression proxy that reduces token usage",
    )
    parser.add_argument(
        "--pipe",
        action="store_true",
        default=False,
        help="Pipe mode: read stdin/file, compress, write stdout (backward compat)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Config file path for proxy mode (YAML)",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Input file path (pipe mode only, reads from stdin if omitted)",
    )
    args = parser.parse_args(argv)

    if args.pipe:
        return _run_pipe(args)

    # Proxy mode
    if args.config is not None:
        config_path = Path(args.config)
        if not config_path.exists():
            print(
                f"Error: config file not found: {args.config}",
                file=sys.stderr,
            )
            return 1

    try:
        return asyncio.run(_run_proxy(args.config))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
