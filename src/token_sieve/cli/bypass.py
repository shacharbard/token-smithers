"""bypass CLI subcommand — D5c Layer 4: manual bypass rule management.

Commands:
    token-sieve bypass add <pattern>    — Add a manual bypass rule
    token-sieve bypass remove <pattern> — Remove a bypass rule
    token-sieve bypass list             — List all active bypass rules
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

# Default learning DB path (same as compress.py / stats uses)
_DEFAULT_LEARNING_DB = os.path.expanduser("~/.token-sieve/learning.db")


def _get_db_path() -> str:
    """Return the learning DB path from env or default."""
    return os.environ.get("TOKEN_SIEVE_LEARNING_DB", _DEFAULT_LEARNING_DB)


def run_bypass(argv: list[str]) -> int:
    """Entry point for the bypass subcommand.

    Args:
        argv: Arguments after 'bypass', e.g. ['add', 'kubectl get secret']

    Returns:
        0 on success, 1 on error.
    """
    if not argv:
        _print_usage()
        return 1

    subcommand = argv[0]
    rest = argv[1:]

    if subcommand == "add":
        return _bypass_add(rest)
    elif subcommand == "remove":
        return _bypass_remove(rest)
    elif subcommand == "list":
        return _bypass_list()
    else:
        print(f"Error: unknown bypass subcommand '{subcommand}'", file=sys.stderr)
        _print_usage()
        return 1


def _print_usage() -> None:
    print(
        "Usage: token-sieve bypass <add|remove|list> [pattern]",
        file=sys.stderr,
    )


def _run_sync(coro) -> object:
    """Run a coroutine synchronously, handling running-loop contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import threading

            result_holder: list = []

            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result_holder.append(new_loop.run_until_complete(coro))
                except Exception as exc:
                    result_holder.append(exc)
                finally:
                    new_loop.close()

            t = threading.Thread(target=run_in_thread, daemon=True)
            t.start()
            t.join(timeout=10)
            if not result_holder:
                return 1
            if isinstance(result_holder[0], Exception):
                raise result_holder[0]
            return result_holder[0]
        else:
            return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _bypass_add(args: list[str]) -> int:
    """Add a manual bypass rule."""
    if not args:
        print("Error: bypass add requires a pattern", file=sys.stderr)
        return 1
    pattern = " ".join(args)
    return _run_sync(_async_bypass_add(pattern))


async def _async_bypass_add(pattern: str) -> int:
    """Async implementation of bypass add."""
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    try:
        store = await SQLiteLearningStore.connect(db_path)
    except Exception as exc:
        print(f"Error: could not open learning store: {exc}", file=sys.stderr)
        return 1

    try:
        now = datetime.now(timezone.utc).isoformat()
        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'manual', ?, ?, 0, 1)
            ON CONFLICT(pattern) DO UPDATE SET
                source = 'manual',
                is_active = 1,
                last_reinforced_at = excluded.last_reinforced_at
            """,
            (pattern, now, now),
        )
        await store._db.commit()
        print(f"Added manual bypass rule: {pattern!r}")
        return 0
    except Exception as exc:
        print(f"Error: failed to add bypass rule: {exc}", file=sys.stderr)
        return 1
    finally:
        await store.close()


def _bypass_remove(args: list[str]) -> int:
    """Remove a bypass rule."""
    if not args:
        print("Error: bypass remove requires a pattern", file=sys.stderr)
        return 1
    pattern = " ".join(args)
    return _run_sync(_async_bypass_remove(pattern))


async def _async_bypass_remove(pattern: str) -> int:
    """Async implementation of bypass remove."""
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    db_path = _get_db_path()

    try:
        store = await SQLiteLearningStore.connect(db_path)
    except Exception as exc:
        print(f"Error: could not open learning store: {exc}", file=sys.stderr)
        return 1

    try:
        await store._db.execute(
            "DELETE FROM bypass_rules WHERE pattern = ?",
            (pattern,),
        )
        await store._db.commit()
        print(f"Removed bypass rule: {pattern!r}")
        return 0
    except Exception as exc:
        print(f"Error: failed to remove bypass rule: {exc}", file=sys.stderr)
        return 1
    finally:
        await store.close()


def _bypass_list() -> int:
    """List all bypass rules."""
    return _run_sync(_async_bypass_list())


async def _async_bypass_list() -> int:
    """Async implementation of bypass list."""
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    db_path = _get_db_path()

    try:
        store = await SQLiteLearningStore.connect(db_path)
    except Exception as exc:
        print(f"Error: could not open learning store: {exc}", file=sys.stderr)
        return 1

    try:
        async with store._db.execute(
            "SELECT pattern, source, last_reinforced_at, session_count, is_active "
            "FROM bypass_rules ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            print("No bypass rules configured.")
            return 0

        print(f"{'Pattern':<40} {'Source':<10} {'Reinforced':<26} {'Active':>6}")
        print(f"{'-' * 40} {'-' * 10} {'-' * 26} {'-' * 6}")
        for row in rows:
            pattern, source, last_reinforced, session_count, is_active = (
                row[0], row[1], row[2], row[3], row[4]
            )
            active_str = "yes" if is_active else "no"
            # Truncate long patterns
            display_pattern = pattern[:38] + ".." if len(pattern) > 40 else pattern
            print(f"{display_pattern:<40} {source:<10} {last_reinforced:<26} {active_str:>6}")

        return 0
    except Exception as exc:
        print(f"Error: failed to list bypass rules: {exc}", file=sys.stderr)
        return 1
    finally:
        await store.close()
