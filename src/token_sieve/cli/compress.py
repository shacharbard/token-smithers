"""CLI compressor entrypoint — wraps a subprocess and compresses its stdout.

Decision D1: CLI owns shell complexity via TSIEV_WRAP_CMD env var.
Decision D1b: Exit code is byte-equal to the wrapped subprocess returncode.
Decision D1c: stderr passes through raw; stdout is the only stream compressed.
Decision D5a: On pipeline exception, emit raw stdout + annotation to stderr.
Decision D5b: Raw stdout recorded to per-session ring buffer before compression.

Usage (invoked by hooks in 09-02):
    TSIEV_WRAP_CMD="<shell command>" token-sieve compress [--wrap-env]
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys

logger = logging.getLogger(__name__)

# Annotation emitted to stderr when compression fails (D5a).
# Format preserved exactly so 09-04 telemetry can grep for this marker.
_FAIL_OPEN_TEMPLATE = (
    "[token-sieve: compression failed ({type}: {msg}), raw output below — please report]"
)

# Commands whose stderr carries structured output that benefits from compression.
# Only the first shell word (literal match) triggers the merge.
_STDERR_MERGE_ALLOWLIST: frozenset[str] = frozenset({"cargo", "docker", "webpack"})


def _session_id() -> str:
    """Return CLAUDE_SESSION_ID env var or 'default' if unset."""
    return os.environ.get("CLAUDE_SESSION_ID", "default")


def _get_ring_buffer():
    """Return a RingBuffer instance keyed to the current session.

    Extracted as a module-level factory so tests can monkeypatch it.
    """
    from token_sieve.adapters.learning.ring_buffer import RingBuffer

    return RingBuffer(session_id=_session_id())


def run(argv: list[str]) -> int:
    """Run the compress subcommand.

    Pops TSIEV_WRAP_CMD from the environment, executes it via bash,
    compresses stdout, passes stderr through (or merges for allowlisted
    binaries), and returns the subprocess exit code.

    Args:
        argv: Remaining CLI arguments after 'compress' subcommand.

    Returns:
        The wrapped subprocess returncode.
    """
    cmd = os.environ.pop("TSIEV_WRAP_CMD", None)
    if not cmd:
        print("Error: TSIEV_WRAP_CMD is not set", file=sys.stderr)
        return 1

    # Determine whether stderr should be merged into compression input
    try:
        first_word = shlex.split(cmd)[0] if cmd.strip() else ""
    except ValueError:
        first_word = ""
    merge_stderr = first_word in _STDERR_MERGE_ALLOWLIST

    # Build env without TSIEV_WRAP_CMD (already popped above)
    clean_env = dict(os.environ)

    result = subprocess.run(
        ["bash", "-c", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env,
    )

    raw_stdout = result.stdout
    raw_stderr = result.stderr

    # Record raw output to ring buffer before compression (D5b).
    # Ring buffer failure must never break compression (isolated try/except).
    try:
        buf = _get_ring_buffer()
        buf.append(raw_stdout)
    except OSError as exc:
        logger.warning("token_sieve ring buffer append failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("token_sieve ring buffer unavailable: %s", exc)

    # Determine compression input
    if merge_stderr:
        compression_input = raw_stdout + ("\n" if raw_stdout and raw_stderr else "") + raw_stderr
        emit_stderr = ""
    else:
        compression_input = raw_stdout
        emit_stderr = raw_stderr

    # Run through the compression pipeline (D5a: fail-open on exception)
    try:
        from token_sieve.cli.main import create_pipeline
        from token_sieve.domain.model import ContentEnvelope, ContentType

        pipeline, _counter = create_pipeline()
        envelope = ContentEnvelope(
            content=compression_input, content_type=ContentType.TEXT
        )
        compressed_envelope, _events = pipeline.process(envelope)
        sys.stdout.write(compressed_envelope.content)
        sys.stdout.flush()
    except Exception as exc:  # noqa: BLE001  — fail-open (D5a)
        annotation = _FAIL_OPEN_TEMPLATE.format(
            type=type(exc).__name__, msg=str(exc)
        )
        sys.stdout.write(compression_input)
        sys.stdout.flush()
        print(annotation, file=sys.stderr)

    # Emit raw stderr (empty string when merged)
    if emit_stderr:
        sys.stderr.write(emit_stderr)
        sys.stderr.flush()

    return result.returncode
