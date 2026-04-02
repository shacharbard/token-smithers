"""CLI entry point for token-sieve.

Two modes:
- **Proxy mode** (default): Start MCP proxy server that Claude Code connects to.
- **Pipe mode** (--pipe): Read stdin, compress, write stdout. Backward compat.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

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
    """Proxy mode: start MCP server with real backend connection.

    Fails fast if no backend command is configured.
    """
    from token_sieve.adapters.backend.connector import BackendConnector
    from token_sieve.adapters.backend.stdio_transport import StdioClientTransport
    from token_sieve.server.proxy import ProxyServer

    if config_path is not None:
        from token_sieve.config.schema import load_config

        path = Path(config_path)
        config = load_config(path)
    else:
        from token_sieve.config.schema import TokenSieveConfig

        config = TokenSieveConfig()

    if not config.backend.command:
        print(
            "Error: backend.command is required for proxy mode. "
            "Configure a backend MCP server command in your config file.",
            file=sys.stderr,
        )
        return 1

    proxy = ProxyServer.create_from_config(config)

    # Wire real backend — replace the stub connector with a live session
    transport = StdioClientTransport(
        command=config.backend.command,
        args=config.backend.args,
        env=config.backend.env or None,
    )
    async with transport.connect() as session:
        connector = BackendConnector(session)
        proxy.rebind_connector(connector)

        # Initialize interception: compress backend instructions
        if (
            config.system_prompt.enabled
            and config.system_prompt.compress_instructions
        ):
            instructions = connector.get_instructions()
            if instructions:
                try:
                    envelope = ContentEnvelope(
                        content=instructions,
                        content_type=ContentType.TEXT,
                    )
                    compressed, _events = proxy._pipeline.process(envelope)
                    connector.set_instructions(compressed.content)
                except Exception:
                    logger.debug("Instruction compression failed, using original")

        await proxy.run()
    return 0


def _run_stats() -> int:
    """Print metrics dashboard from metrics.json file."""
    import json
    import os

    metrics_path = os.environ.get(
        "TOKEN_SIEVE_METRICS_PATH",
        os.path.expanduser("~/.token-sieve/metrics.json"),
    )

    if not Path(metrics_path).exists():
        print(
            f"Error: no metrics file found at {metrics_path}",
            file=sys.stderr,
        )
        return 1

    try:
        data = json.loads(Path(metrics_path).read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: failed to read metrics: {exc}", file=sys.stderr)
        return 1

    summary = data.get("session_summary", {})
    breakdown = data.get("strategy_breakdown", {})

    ratio = summary.get("total_savings_ratio", 0)
    original = summary.get("total_original_tokens", 0)
    compressed = summary.get("total_compressed_tokens", 0)
    saved = original - compressed

    # Burns personality based on savings
    if ratio >= 0.4:
        quote = '"Excellent..."'
        comment = f"Smithers, we saved {saved:,} tokens. Not a single one squandered."
    elif ratio >= 0.2:
        quote = '"Very good, Smithers."'
        comment = f"{saved:,} tokens saved. Acceptable, but I expect more next session."
    elif ratio > 0:
        quote = '"Smithers, this is barely adequate."'
        comment = f"Only {saved:,} tokens saved. We can do better. Enable more adapters."
    else:
        quote = '"Smithers, this is unacceptable."'
        comment = "No savings recorded. Check your configuration."

    print()
    print(f"  {quote}")
    print()
    print("  === Token Smithers — Session Stats ===")
    print(f"  Events:     {summary.get('event_count', 0)}")
    print(f"  Original:   {original:,} tokens")
    print(f"  Compressed: {compressed:,} tokens")
    print(f"  Saved:      {saved:,} tokens ({ratio:.1%})")
    print()
    print(f"  {comment}")
    print()

    if breakdown:
        print("  === Per-Strategy Breakdown ===")
        print(f"  {'Strategy':<30} {'Count':>6} {'Original':>10} {'Compressed':>10}")
        print(f"  {'-' * 30} {'-' * 6} {'-' * 10} {'-' * 10}")
        for name, stats in sorted(breakdown.items()):
            print(
                f"  {name:<30} {stats['count']:>6} "
                f"{stats['total_original_tokens']:>10} "
                f"{stats['total_compressed_tokens']:>10}"
            )
        print()

    return 0


def _run_status_line() -> int:
    """Print a one-liner for status bar integration."""
    import json
    import os

    metrics_path = os.environ.get(
        "TOKEN_SIEVE_METRICS_PATH",
        os.path.expanduser("~/.token-sieve/metrics.json"),
    )

    if not Path(metrics_path).exists():
        print("Smithers: awaiting first call...")
        return 0

    try:
        data = json.loads(Path(metrics_path).read_text())
    except (json.JSONDecodeError, OSError):
        print("Smithers: metrics unavailable")
        return 0

    summary = data.get("session_summary", {})
    ratio = summary.get("total_savings_ratio", 0)
    original = summary.get("total_original_tokens", 0)
    compressed = summary.get("total_compressed_tokens", 0)
    saved = original - compressed

    if saved == 0:
        print("Smithers: no savings yet")
    elif ratio >= 0.4:
        print(f"Smithers saved {saved:,} tokens ({ratio:.0%}) | Excellent...")
    elif ratio >= 0.2:
        print(f"Smithers saved {saved:,} tokens ({ratio:.0%}) | Very good.")
    elif ratio > 0:
        print(f"Smithers saved {saved:,} tokens ({ratio:.0%}) | Barely adequate.")
    else:
        print(f"Smithers: {saved:,} tokens | Unacceptable.")

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, dispatch to proxy, pipe, or stats mode.

    Returns 0 on success, 1 on error.
    """
    # Check for stats subcommand before argparse (avoids positional conflict)
    effective_argv = argv if argv is not None else sys.argv[1:]
    if effective_argv and effective_argv[0] == "stats":
        return _run_stats()

    if effective_argv and effective_argv[0] == "status-line":
        return _run_status_line()

    if effective_argv and effective_argv[0] == "setup":
        from token_sieve.cli.setup import run_setup

        undo = "--undo" in effective_argv
        return run_setup(undo=undo)

    parser = argparse.ArgumentParser(
        prog="token-smithers",
        description="Token Smithers — your loyal assistant for token efficiency",
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
    except asyncio.CancelledError:
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.exception("Proxy failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
