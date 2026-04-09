"""RED tests for BypassStore — auto-learn, decay, CI detection, reinforcement.

Task 2 of 09-04: verify the full D5c bypass logic including inline-vs-inherited
distinction, 5-in-14-days auto-learn, most-specific-prefix, CI detection, dual
decay (20 sessions or 90 days), active+passive reinforcement, manual rules.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from token_sieve.adapters.learning.bypass_store import BypassStore
from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore


@pytest.fixture()
async def store_and_bypass():
    """Create an in-memory SQLiteLearningStore + BypassStore pair."""
    s = await SQLiteLearningStore.connect(":memory:")
    bs = BypassStore(store=s)
    try:
        yield s, bs
    finally:
        await s.close()


class TestBypassStoreInlineRecording:
    """Tests for inline bypass event recording."""

    async def test_record_inline_bypass_creates_event(self, store_and_bypass) -> None:
        """record_inline_bypass creates one bypass_events row with kind='inline'."""
        store, bs = store_and_bypass
        await bs.record_inline_bypass("pytest tests/auth", session_id="s1")

        async with store._db.execute(
            "SELECT kind, session_id FROM bypass_events"
        ) as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "inline"
        assert rows[0][1] == "s1"

    async def test_inherited_bypass_does_not_count(self, store_and_bypass) -> None:
        """record_inherited_bypass should NOT create any bypass_events row."""
        store, bs = store_and_bypass
        await bs.record_inherited_bypass("pytest tests/auth", session_id="s1")

        async with store._db.execute("SELECT COUNT(*) FROM bypass_events") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0


class TestBypassAutoLearn:
    """Tests for the 10-in-14-days auto-learn trigger (C2 fix raised from 5)."""

    async def test_auto_learn_after_10_inline_bypasses(self, store_and_bypass) -> None:
        """10 inline events from ≥2 distinct sessions → 1 bypass_rules row."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        # Record 10 inline bypasses within 14 days, alternating between 2 sessions
        for i in range(10):
            event_time = now - timedelta(hours=i)
            await bs.record_inline_bypass(
                "pytest tests/auth/test_login.py",
                session_id=f"s{i % 2}",  # two distinct session ids
                occurred_at=event_time,
            )

        async with store._db.execute(
            "SELECT pattern, source FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1, "Should have auto-learned exactly 1 rule"
        assert rows[0][1] == "learned"

    async def test_auto_learn_uses_most_specific_prefix(self, store_and_bypass) -> None:
        """Different file args for same base command → learned pattern is common prefix."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        cmds = [
            "pytest tests/auth/test_a.py",
            "pytest tests/auth/test_b.py",
            "pytest tests/auth/test_c.py",
            "pytest tests/auth/test_d.py",
            "pytest tests/auth/test_e.py",
            "pytest tests/auth/test_f.py",
            "pytest tests/auth/test_g.py",
            "pytest tests/auth/test_h.py",
            "pytest tests/auth/test_i.py",
            "pytest tests/auth/test_j.py",
        ]
        for i, cmd in enumerate(cmds):
            await bs.record_inline_bypass(
                cmd,
                session_id=f"s{i % 2}",  # two distinct sessions
                occurred_at=now - timedelta(hours=i),
            )

        async with store._db.execute(
            "SELECT pattern FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        # The common prefix for these commands is "pytest tests/auth"
        assert row[0] == "pytest tests/auth"

    async def test_auto_learn_NOT_triggered_with_9_events(self, store_and_bypass) -> None:
        """9 inline events should NOT trigger auto-learn (threshold is 10)."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        for i in range(9):
            await bs.record_inline_bypass(
                "pytest tests/auth",
                session_id=f"s{i % 2}",
                occurred_at=now - timedelta(hours=i),
            )

        async with store._db.execute(
            "SELECT COUNT(*) FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0, "Should not auto-learn after only 9 events"

    async def test_auto_learn_NOT_triggered_outside_14_days(self, store_and_bypass) -> None:
        """10 events spanning 15+ days should NOT trigger auto-learn."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        # Spread 10 events across 18 days (too wide)
        for i in range(10):
            await bs.record_inline_bypass(
                "pytest tests/auth",
                session_id=f"s{i % 2}",
                occurred_at=now - timedelta(days=i * 2),  # days 0,2,...,18
            )

        async with store._db.execute(
            "SELECT COUNT(*) FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0, "Should not auto-learn when events span >14 days"

    async def test_auto_learn_NOT_triggered_from_single_session(self, store_and_bypass) -> None:
        """C2 fix: 10+ events from a single session_id should NOT auto-learn.

        Requires evidence from ≥2 distinct sessions so one runaway loop can't
        mint a permanent rule.
        """
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        for i in range(15):
            await bs.record_inline_bypass(
                "pytest tests/auth",
                session_id="only-one-session",
                occurred_at=now - timedelta(hours=i),
            )

        async with store._db.execute(
            "SELECT COUNT(*) FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0, "Should not auto-learn from a single session_id"

    async def test_cmd_matches_pattern_no_substring_overmatch(self) -> None:
        """C2 fix: bare startswith must not match non-separator prefixes.

        `pytest tests/auth` should NOT match `pytest tests/authority_tests.py`
        because the match boundary is a path separator, not a string prefix.
        """
        from token_sieve.adapters.learning.bypass_store import _cmd_matches_pattern

        assert _cmd_matches_pattern(
            "pytest tests/auth/test_a.py", "pytest tests/auth"
        ) is True, "separator-anchored prefix must still match"
        assert _cmd_matches_pattern(
            "pytest tests/auth", "pytest tests/auth"
        ) is True, "exact match must still match"
        assert _cmd_matches_pattern(
            "pytest tests/authority_tests.py", "pytest tests/auth"
        ) is False, "bare string prefix must NOT match"
        assert _cmd_matches_pattern(
            "kubectl get secret", "kubectl g"
        ) is False, "bare word prefix must NOT match"

    async def test_concurrent_record_inline_bypass_no_integrity_error(
        self, store_and_bypass
    ) -> None:
        """H8 fix: concurrent `record_inline_bypass` calls on the same pattern
        must not raise IntegrityError and must result in exactly one rule.

        Before the fix, the auto-learn path did SELECT-then-INSERT across
        separate commits, so two concurrent callers could both pass the
        existence check and both INSERT, with the second raising
        IntegrityError on the PK constraint.
        """
        import asyncio

        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        # Pre-load 9 events so the next two concurrent record_inline_bypass
        # calls both cross the 10-event threshold simultaneously.
        for i in range(9):
            await bs.record_inline_bypass(
                "pytest tests/auth/test_a.py",
                session_id=f"s{i % 2}",
                occurred_at=now - timedelta(hours=i + 1),
            )

        # Now fire two concurrent calls that would each push the count to 10+.
        await asyncio.gather(
            bs.record_inline_bypass(
                "pytest tests/auth/test_b.py",
                session_id="sX",
                occurred_at=now,
            ),
            bs.record_inline_bypass(
                "pytest tests/auth/test_c.py",
                session_id="sY",
                occurred_at=now,
            ),
        )

        async with store._db.execute(
            "SELECT COUNT(*) FROM bypass_rules WHERE source='learned'"
        ) as cursor:
            row = await cursor.fetchone()
        # Must be exactly 1 — not 0 (IntegrityError swallowed incorrectly)
        # and not 2 (duplicate INSERTs).
        assert row[0] == 1, f"Expected exactly 1 learned rule, got {row[0]}"

    async def test_most_specific_prefix_rejects_non_path_substrings(self) -> None:
        """C2 fix: `_most_specific_prefix` must not mint `pytest t` from divergent tokens."""
        from token_sieve.adapters.learning.bypass_store import _most_specific_prefix

        # Diverging after "pytest": "tests/a" vs "test_utils/b" share "t" but
        # no full path component — must NOT return "pytest t".
        result = _most_specific_prefix([
            "pytest tests/auth/test_login.py",
            "pytest test_utils/helpers.py",
        ])
        assert result in ("", "pytest"), (
            f"common prefix must not be a bare substring, got {result!r}"
        )

    async def test_ci_detection_skips_auto_learn(self, store_and_bypass) -> None:
        """When CI=true, record_inline_bypass returns early without recording any event."""
        store, bs = store_and_bypass

        with patch.dict("os.environ", {"CI": "true"}):
            await bs.record_inline_bypass("pytest tests/auth", session_id="s1")

        async with store._db.execute("SELECT COUNT(*) FROM bypass_events") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0, "CI detection should skip event recording entirely"


class TestBypassDecay:
    """Tests for the dual decay model (20 sessions or 90 calendar days)."""

    async def test_decay_after_20_sessions_of_non_reinforcement(
        self, store_and_bypass
    ) -> None:
        """Rule with last_reinforced session=1; 20 distinct non-reinforcing sessions → is_active=False."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)

        # Create a learned rule manually
        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 0, 1)
            """,
            ("pytest tests/auth", now.isoformat(), now.isoformat()),
        )
        await store._db.commit()

        # Record 20 distinct sessions without reinforcement for this pattern
        for i in range(20):
            await bs.record_non_reinforcement_session(
                "pytest tests/auth", session_id=f"other-{i}"
            )

        # Check decay
        await bs.check_and_decay("pytest tests/auth")

        async with store._db.execute(
            "SELECT is_active FROM bypass_rules WHERE pattern=?",
            ("pytest tests/auth",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0, "Rule should be decayed after 20 non-reinforcement sessions"

    async def test_decay_after_90_day_calendar_fallback(self, store_and_bypass) -> None:
        """Rule with last_reinforced 91 days ago → is_active=False (calendar decay)."""
        store, bs = store_and_bypass
        old_time = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 0, 1)
            """,
            ("pytest tests/old", old_time, old_time),
        )
        await store._db.commit()

        await bs.check_and_decay("pytest tests/old")

        async with store._db.execute(
            "SELECT is_active FROM bypass_rules WHERE pattern=?",
            ("pytest tests/old",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0, "Rule should be decayed after 90 calendar days"


class TestBypassReinforcement:
    """Tests for active and passive reinforcement."""

    async def test_active_reinforcement_via_inline_bypass(self, store_and_bypass) -> None:
        """Re-issuing NO_COMPRESS=1 for a learned pattern updates last_reinforced + session_count."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(days=10)).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 3, 1)
            """,
            ("pytest tests/auth", old_time, old_time),
        )
        await store._db.commit()

        await bs.record_inline_bypass("pytest tests/auth/new_test.py", session_id="s-reinforce")

        async with store._db.execute(
            "SELECT last_reinforced_at, session_count FROM bypass_rules WHERE pattern=?",
            ("pytest tests/auth",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] > old_time, "last_reinforced_at should be updated"
        assert row[1] > 3, "session_count should increase"

    async def test_passive_reinforcement_via_silent_fire(self, store_and_bypass) -> None:
        """rule fires (compression silently skipped) → counts as reinforcement."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(days=10)).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 2, 1)
            """,
            ("pytest tests/auth", old_time, old_time),
        )
        await store._db.commit()

        await bs.record_passive_reinforcement("pytest tests/auth", session_id="s-passive")

        async with store._db.execute(
            "SELECT last_reinforced_at, session_count FROM bypass_rules WHERE pattern=?",
            ("pytest tests/auth",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] > old_time, "last_reinforced_at should be updated on passive reinforce"
        assert row[1] > 2, "session_count should increase on passive reinforce"


class TestBypassLookup:
    """Tests for is_bypassed() lookup."""

    async def test_is_bypassed_returns_true_for_active_rule(self, store_and_bypass) -> None:
        """Active learned rule → is_bypassed returns True."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 5, 1)
            """,
            ("pytest tests/auth", now, now),
        )
        await store._db.commit()

        result = await bs.is_bypassed("pytest tests/auth/test_x.py")
        assert result is True

    async def test_is_bypassed_returns_false_for_decayed_rule(self, store_and_bypass) -> None:
        """Decayed rule (is_active=0) → is_bypassed returns False."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 0, 0)
            """,
            ("pytest tests/auth", now, now),
        )
        await store._db.commit()

        result = await bs.is_bypassed("pytest tests/auth/test_x.py")
        assert result is False

    async def test_is_bypassed_respects_manual_rules(self, store_and_bypass) -> None:
        """Manually-added rule → is_bypassed returns True (decay only affects learned rules)."""
        store, bs = store_and_bypass
        now = datetime.now(timezone.utc).isoformat()

        await store._db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'manual', ?, ?, 0, 1)
            """,
            ("kubectl get secret", now, now),
        )
        await store._db.commit()

        result = await bs.is_bypassed("kubectl get secret mysecret -o yaml")
        assert result is True

    async def test_is_bypassed_returns_false_when_no_rule(self, store_and_bypass) -> None:
        """No matching rule → is_bypassed returns False."""
        _store, bs = store_and_bypass
        result = await bs.is_bypassed("pytest tests/")
        assert result is False
