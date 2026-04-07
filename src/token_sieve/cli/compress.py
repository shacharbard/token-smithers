"""CLI compressor entrypoint — wraps a subprocess and compresses its stdout.

Decision D1: CLI owns shell complexity via TSIEV_WRAP_CMD env var.
Decision D1b: Exit code is byte-equal to the wrapped subprocess returncode.
Decision D1c: stderr passes through raw; stdout is the only stream compressed.
Decision D2: Retry detection — bypass compression on consecutive same-command.
Decision D3: Shadow logging — adaptive sampling of compression telemetry.
Decision D4c: Determinism preserved — shadow sampling never alters Claude's bytes.
Decision D5a: On pipeline exception, emit raw stdout + annotation to stderr.
Decision D5b: Raw stdout recorded to per-session ring buffer before compression.

Usage (invoked by hooks in 09-02):
    TSIEV_WRAP_CMD="<shell command>" token-sieve compress [--wrap-env]

Escape hatches (D2f):
    TOKEN_SIEVE_RETRY_DISABLE_RULE=off  — disable retry detection entirely
    TOKEN_SIEVE_RETRY_THRESHOLD_PINNED=N — override consecutive threshold
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import sys

from token_sieve.cli._session import session_id as _session_id

logger = logging.getLogger(__name__)


def _run_async(coro) -> None:
    """Run a coroutine synchronously, handling both fresh and running event loops.

    When called from within a running event loop (e.g., pytest-asyncio tests),
    schedules the coroutine as a task on the running loop using run_coroutine_threadsafe.
    When no loop is running, creates a new one via asyncio.run().
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Running inside an existing loop (e.g., test environment)
            import concurrent.futures

            future = asyncio.run_coroutine_threadsafe(coro, loop)
            future.result(timeout=5)
        else:
            asyncio.run(coro)
    except RuntimeError:
        # No event loop at all — create one
        asyncio.run(coro)


def _run_async_bool(coro_or_val) -> bool:
    """Run an async coroutine that returns bool, defaulting to False on error.

    Also handles synchronous values (non-coroutines) for test compatibility.
    """
    import inspect

    if not inspect.isawaitable(coro_or_val):
        # Already a plain value (e.g., synchronous mock in tests)
        return bool(coro_or_val)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Running in async context (e.g., pytest-asyncio).
            # Spin a new event loop in a daemon thread to avoid deadlock.
            import threading

            result_holder: list = []

            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result_holder.append(new_loop.run_until_complete(coro_or_val))
                except Exception:  # noqa: BLE001
                    result_holder.append(False)
                finally:
                    new_loop.close()

            t = threading.Thread(target=run_in_thread, daemon=True)
            t.start()
            t.join(timeout=5)
            return bool(result_holder[0]) if result_holder else False
        else:
            return bool(asyncio.run(coro_or_val))
    except Exception:  # noqa: BLE001
        return False


def _bypass_and_run_raw(cmd: str) -> int:
    """Run cmd via bash and write raw stdout without compression.

    Used by all D5c bypass layers (denylist, env var, learned rules).
    """
    clean_env = dict(os.environ)
    result = subprocess.run(
        ["bash", "-c", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env,
    )
    sys.stdout.write(result.stdout)
    sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()
    return result.returncode


# Annotation emitted to stderr when compression fails (D5a).
# Format preserved exactly so 09-04 telemetry can grep for this marker.
_FAIL_OPEN_TEMPLATE = (
    "[token-sieve: compression failed ({type}: {msg}), raw output below — please report]"
)

# Commands whose stderr carries structured output that benefits from compression.
# Only the first shell word (literal match) triggers the merge.
_STDERR_MERGE_ALLOWLIST: frozenset[str] = frozenset({"cargo", "docker", "webpack"})

# Default learning DB path (same as main.py / stats uses)
_DEFAULT_LEARNING_DB = os.path.expanduser("~/.token-sieve/learning.db")


def _get_ring_buffer():
    """Return a RingBuffer instance keyed to the current session.

    Extracted as a module-level factory so tests can monkeypatch it.
    """
    from token_sieve.adapters.learning.ring_buffer import RingBuffer

    return RingBuffer(session_id=_session_id())


def _get_retry_detector():
    """Return a RetryDetector instance (module-level singleton-ish via cache).

    Extracted as a factory so tests can monkeypatch it.
    The 90s default window is the spec default; TOKEN_SIEVE_RETRY_THRESHOLD_PINNED
    does not change window_seconds — it is an escape hatch for future use.
    """
    from token_sieve.adapters.learning.retry_detector import RetryDetector

    return RetryDetector(window_seconds=90)


def _get_learning_store():
    """Return an async SQLiteLearningStore connected to the default learning DB.

    Returns None if the DB cannot be opened (fail-safe).
    Extracted as a factory so tests can monkeypatch it.
    """
    import asyncio

    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    try:
        db_path = os.environ.get("TOKEN_SIEVE_LEARNING_DB", _DEFAULT_LEARNING_DB)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return asyncio.get_event_loop().run_until_complete(
            SQLiteLearningStore.connect(db_path)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("token_sieve: could not open learning store: %s", exc)
        return None


def _get_shadow_logger():
    """Return a ShadowLogger bound to the default learning store.

    Returns None if the store is unavailable (fail-safe).
    Extracted as a factory so tests can monkeypatch it.
    """
    from token_sieve.adapters.learning.shadow_logger import ShadowLogger

    store = _get_learning_store()
    if store is None:
        return None
    return ShadowLogger(store=store)


def _get_bypass_store():
    """Return a BypassStore bound to the default learning store.

    Returns None if the store is unavailable (fail-safe).
    Extracted as a factory so tests can monkeypatch it.
    """
    from token_sieve.adapters.learning.bypass_store import BypassStore

    store = _get_learning_store()
    if store is None:
        return None
    return BypassStore(store=store)


def run(argv: list[str]) -> int:
    """Run the compress subcommand.

    Pops TSIEV_WRAP_CMD from the environment, executes it via bash,
    checks for retries (D2), compresses stdout (or bypasses on retry),
    passes stderr through (or merges for allowlisted binaries), shadow-logs
    the result (D3), and returns the subprocess exit code.

    Args:
        argv: Remaining CLI arguments after 'compress' subcommand.

    Returns:
        The wrapped subprocess returncode.
    """
    cmd = os.environ.pop("TSIEV_WRAP_CMD", None)
    if not cmd:
        print("Error: TSIEV_WRAP_CMD is not set", file=sys.stderr)
        return 1

    # --- D5c Layer 1: built-in sensitive denylist (checked BEFORE everything) ---
    try:
        from token_sieve.adapters.learning import sensitive_denylist

        if sensitive_denylist.matches(cmd):
            return _bypass_and_run_raw(cmd)
    except Exception as exc:  # noqa: BLE001
        logger.debug("token_sieve: denylist check failed: %s", exc)

    # --- D5c Layers 2+3: env var bypass + auto-learn recording ---
    inline_bypass = os.environ.get("TSIEV_INLINE_NO_COMPRESS") == "1"
    inherited_bypass = (
        os.environ.get("NO_COMPRESS") == "1" and not inline_bypass
    )

    # CI detection — skip auto-learn recording in CI environments (D5c)
    _ci_env_vars = ("CI", "GITHUB_ACTIONS", "CI_PIPELINE_ID")
    is_ci = any(os.environ.get(v, "") for v in _ci_env_vars)

    if inline_bypass or inherited_bypass:
        # Record inline event for auto-learn (CI detection: skip if in CI)
        if inline_bypass and not is_ci:
            try:
                bypass_store = _get_bypass_store()
                if bypass_store is not None:
                    _run_async(
                        bypass_store.record_inline_bypass(cmd, session_id=_session_id())
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("token_sieve: bypass store record failed: %s", exc)
        return _bypass_and_run_raw(cmd)

    # --- D5c Layer 3: learned rules check ---
    try:
        bypass_store = _get_bypass_store()
        if bypass_store is not None:
            is_rule_bypass = _run_async_bool(bypass_store.is_bypassed(cmd))
            if is_rule_bypass:
                _run_async(
                    bypass_store.record_passive_reinforcement(cmd, session_id=_session_id())
                )
                return _bypass_and_run_raw(cmd)
    except Exception as exc:  # noqa: BLE001
        logger.debug("token_sieve: bypass store lookup failed: %s", exc)

    # Read escape hatches (D2f)
    retry_rule_off = os.environ.get("TOKEN_SIEVE_RETRY_DISABLE_RULE", "").lower() == "off"

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

    # --- Retry detection (D2) ---
    is_retry = False
    if not retry_rule_off:
        try:
            det = _get_retry_detector()
            is_retry = det.record_command(cmd)
        except Exception as exc:  # noqa: BLE001  — never break compress on detection failure
            logger.debug("token_sieve retry detector failed: %s", exc)

    # Determine compression input
    if merge_stderr:
        compression_input = raw_stdout + ("\n" if raw_stdout and raw_stderr else "") + raw_stderr
        emit_stderr = ""
    else:
        compression_input = raw_stdout
        emit_stderr = raw_stderr

    compressed_bytes = len(compression_input.encode())  # fallback if pipeline skipped

    if is_retry:
        # D2c: bypass compression entirely on retry — write raw output
        sys.stdout.write(compression_input)
        sys.stdout.flush()

        # Record the retry event in the learning DB (fire-and-forget)
        try:
            from token_sieve.adapters.learning.retry_detector import normalize_pattern_hash

            pattern_hash = normalize_pattern_hash(cmd)
            store = _get_learning_store()
            if store is not None:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).isoformat()
                _run_async(_write_retry_event(store, pattern_hash, now))
        except Exception as exc:  # noqa: BLE001
            logger.debug("token_sieve: retry event write failed: %s", exc)
    else:
        # Normal path: run through the compression pipeline (D5a: fail-open)
        try:
            from token_sieve.cli.main import create_pipeline
            from token_sieve.domain.model import ContentEnvelope, ContentType

            pipeline, _counter = create_pipeline()
            envelope = ContentEnvelope(
                content=compression_input, content_type=ContentType.TEXT
            )
            compressed_envelope, _events = pipeline.process(envelope)
            compressed_bytes = len(compressed_envelope.content.encode())
            sys.stdout.write(compressed_envelope.content)
            sys.stdout.flush()
        except Exception as exc:  # noqa: BLE001  — fail-open (D5a)
            annotation = _FAIL_OPEN_TEMPLATE.format(
                type=type(exc).__name__, msg=str(exc)
            )
            sys.stdout.write(compression_input)
            sys.stdout.flush()
            print(annotation, file=sys.stderr)
            # D5d: record fail-open telemetry to learning DB
            try:
                from token_sieve.adapters.learning.retry_detector import normalize_pattern_hash

                fail_store = _get_learning_store()
                if fail_store is not None:
                    _run_async(
                        _write_compression_error(
                            fail_store,
                            adapter_name="compress_cli",
                            exc_type=type(exc).__name__,
                            pattern_hash=normalize_pattern_hash(cmd),
                        )
                    )
            except Exception as inner_exc:  # noqa: BLE001
                logger.debug("token_sieve: fail-open telemetry write failed: %s", inner_exc)

    # --- Shadow logging (D3) — fire-and-forget, MUST NOT alter Claude's bytes ---
    try:
        shadow = _get_shadow_logger()
        if shadow is not None:
            from token_sieve.adapters.learning.retry_detector import normalize_pattern_hash

            pattern_hash = normalize_pattern_hash(cmd)
            _run_async(
                shadow.maybe_log(
                    pattern_hash=pattern_hash,
                    adapter_name="compress_cli",
                    raw_bytes=compression_input.encode(),
                    compressed_bytes=compressed_bytes,
                    is_retry=is_retry,
                )
            )
    except Exception as exc:  # noqa: BLE001  — D4c: never affect output
        logger.debug("token_sieve shadow logger failed: %s", exc)

    # Emit raw stderr (empty string when merged)
    if emit_stderr:
        sys.stderr.write(emit_stderr)
        sys.stderr.flush()

    return result.returncode


async def _write_retry_event(store, pattern_hash: str, occurred_at: str) -> None:
    """Write a single retry_events row to the learning store."""
    await store._db.execute(
        """
        INSERT INTO retry_events (pattern_hash, occurred_at, threshold_at_event, session_id)
        VALUES (?, ?, ?, ?)
        """,
        (pattern_hash, occurred_at, 5, _session_id()),
    )
    await store._db.commit()


async def _write_compression_error(
    store,
    adapter_name: str,
    exc_type: str,
    pattern_hash: str,
) -> None:
    """Write a fail-open telemetry row to compression_errors table (D5d).

    The table is created on first use (CREATE TABLE IF NOT EXISTS) so that
    existing databases don't require a schema migration just for this.
    """
    from datetime import datetime, timezone

    # Ensure table exists (idempotent)
    await store._db.execute(
        """
        CREATE TABLE IF NOT EXISTS compression_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_name TEXT NOT NULL,
            exc_type TEXT NOT NULL,
            pattern_hash TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            session_id TEXT NOT NULL
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    await store._db.execute(
        """
        INSERT INTO compression_errors (adapter_name, exc_type, pattern_hash, occurred_at, session_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (adapter_name, exc_type, pattern_hash, now, _session_id()),
    )
    await store._db.commit()
