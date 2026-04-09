"""RED tests for M3 — _run_async / _run_async_bool modernization.

Current code uses asyncio.get_event_loop() which is deprecated in 3.12+
and will raise in 3.14. It also leaks daemon threads on the 5s timeout
in _run_async_bool. Fix: use a small module-level ThreadPoolExecutor +
asyncio.run(), with bounded future.result(timeout=5) that cleans up.
"""
from __future__ import annotations

import asyncio
import threading
import warnings

import pytest

from token_sieve.cli import compress as compress_mod


class TestNoDeprecationWarning:
    def test_run_async_does_not_warn(self):
        """_run_async on a trivial coroutine must not emit DeprecationWarning."""
        async def noop():
            return None

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compress_mod._run_async(noop())

        deprecation = [
            w
            for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "get_event_loop" in str(w.message)
        ]
        assert not deprecation, (
            f"_run_async emitted get_event_loop DeprecationWarning: "
            f"{[str(w.message) for w in deprecation]!r}"
        )

    def test_run_async_bool_does_not_warn(self):
        async def returns_true():
            return True

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = compress_mod._run_async_bool(returns_true())

        assert result is True
        deprecation = [
            w
            for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "get_event_loop" in str(w.message)
        ]
        assert not deprecation


class TestNoThreadLeak:
    def test_run_async_bool_does_not_leak_threads(self):
        """Running _run_async_bool many times must not grow thread count."""
        async def returns_value():
            return True

        before = set(threading.enumerate())

        for _ in range(20):
            assert compress_mod._run_async_bool(returns_value()) is True

        after = set(threading.enumerate())

        # There may be one persistent executor thread (acceptable). But
        # we must not see 20 orphan threads lingering around.
        leaked = after - before
        assert len(leaked) < 5, (
            f"_run_async_bool leaked {len(leaked)} threads over 20 invocations: "
            f"{[t.name for t in leaked]!r}"
        )


class TestRunAsyncBoolSynchronousPassthrough:
    """_run_async_bool must still accept non-awaitable values (test compat)."""

    def test_sync_value_returns_bool(self):
        assert compress_mod._run_async_bool(True) is True
        assert compress_mod._run_async_bool(False) is False
        assert compress_mod._run_async_bool(1) is True

    def test_sync_value_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compress_mod._run_async_bool(True)
        deprecation = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert not deprecation


class TestRunAsyncInsideRunningLoop:
    """When called from inside a running loop, both helpers must not deadlock."""

    @pytest.mark.asyncio
    async def test_run_async_inside_running_loop(self):
        async def coro():
            await asyncio.sleep(0)
            return None

        compress_mod._run_async(coro())

    @pytest.mark.asyncio
    async def test_run_async_bool_inside_running_loop(self):
        async def coro():
            await asyncio.sleep(0)
            return True

        result = compress_mod._run_async_bool(coro())
        assert result is True
