"""BypassStore — D5c Layers 2, 3, and 4 implementation.

Manages bypass rules (manual + auto-learned), inline bypass event recording,
and decay logic. Works on top of the SQLiteLearningStore (v7 schema).

Design decisions:
- Inline vs inherited bypass: only inline (user-typed NO_COMPRESS=1 in command)
  events are recorded and count toward auto-learn; inherited (parent env) don't.
- CI detection: if CI / GITHUB_ACTIONS / CI_PIPELINE_ID are set, skip recording.
- Auto-learn: 5 inline events for the same most-specific argv prefix within 14
  calendar days → write a learned bypass_rules row.
- Decay: learned rules expire when either (a) 20 distinct sessions fire without
  reinforcement, or (b) 90 calendar days pass since last reinforcement.
- Manual rules are immune to decay (source='manual').
"""
from __future__ import annotations

import os
import shlex
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

# Environment variables that indicate CI context — skip auto-learn when any is set.
_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "CI_PIPELINE_ID")

# Auto-learn thresholds
_AUTO_LEARN_THRESHOLD = 5        # inline events needed
_AUTO_LEARN_WINDOW_DAYS = 14     # calendar window
_DECAY_SESSION_THRESHOLD = 20    # distinct non-reinforcing sessions
_DECAY_CALENDAR_DAYS = 90        # calendar days since last reinforcement


def _is_ci() -> bool:
    """Return True if any CI environment variable is set and non-empty."""
    return any(os.environ.get(v, "") for v in _CI_ENV_VARS)


def _parse_argv(cmd: str) -> list[str]:
    """Parse a command string into argv tokens, returning [] on error."""
    try:
        return shlex.split(cmd)
    except ValueError:
        return []


def _most_specific_prefix(cmds: list[str]) -> str:
    """Compute the longest common positional argv prefix across a list of commands.

    For fully identical tokens, includes them whole.  For the first diverging
    token, computes the common string prefix (e.g. "tests/auth/test_a.py" and
    "tests/auth/test_b.py" → "tests/auth") and appends it if non-empty.

    Args:
        cmds: List of shell command strings.

    Returns:
        The longest common prefix as a space-joined string, e.g. "pytest tests/auth".
        Returns empty string if cmds is empty or no common prefix exists.
    """
    import os

    if not cmds:
        return ""

    parsed = [_parse_argv(c) for c in cmds]
    parsed = [p for p in parsed if p]  # drop empties
    if not parsed:
        return ""

    # Find fully-matching prefix tokens
    min_len = min(len(p) for p in parsed)
    prefix_tokens: list[str] = []
    for i in range(min_len):
        token = parsed[0][i]
        if all(p[i] == token for p in parsed):
            prefix_tokens.append(token)
        else:
            # Try a common string prefix on this diverging token position
            common_str = os.path.commonprefix([p[i] for p in parsed])
            # Strip trailing path separators or partial word fragments
            # so we don't end up with "tests/auth/test_" — trim to last separator
            if "/" in common_str:
                common_str = common_str.rsplit("/", 1)[0]
            elif common_str and not all(p[i].startswith(common_str) for p in parsed):
                common_str = ""
            if common_str:
                prefix_tokens.append(common_str)
            break

    if not prefix_tokens:
        return ""

    return " ".join(prefix_tokens)


def _cmd_matches_pattern(cmd: str, pattern: str) -> bool:
    """Return True if cmd's argv starts with pattern's argv tokens.

    Matching is done token-by-token for fully-specified tokens.  The last
    pattern token is matched as a path prefix so that a pattern like
    "pytest tests/auth" matches "pytest tests/auth/test_x.py".
    """
    cmd_argv = _parse_argv(cmd)
    pat_argv = _parse_argv(pattern)
    if not pat_argv or not cmd_argv:
        return False

    # All tokens except the last must match exactly
    full_tokens = pat_argv[:-1]
    last_pat = pat_argv[-1]

    n = len(full_tokens)
    if len(cmd_argv) < n + 1:
        return False
    if cmd_argv[:n] != full_tokens:
        return False

    # Last pattern token: exact match OR the corresponding cmd token starts
    # with it (path-prefix match).
    cmd_last = cmd_argv[n]
    return cmd_last == last_pat or cmd_last.startswith(last_pat + "/") or cmd_last.startswith(last_pat)


class BypassStore:
    """Manages bypass rules and events for D5c escape hatch.

    Args:
        store: An open SQLiteLearningStore instance (must have v7 schema).
    """

    def __init__(self, store: SQLiteLearningStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    async def record_inline_bypass(
        self,
        cmd: str,
        session_id: str,
        occurred_at: datetime | None = None,
    ) -> None:
        """Record an inline NO_COMPRESS=1 bypass event.

        Skips recording entirely when running in a CI environment.
        After recording, checks whether auto-learn threshold is reached.

        Args:
            cmd: The original shell command string.
            session_id: Current session identifier.
            occurred_at: Override event timestamp (defaults to now UTC).
        """
        if _is_ci():
            return

        now = occurred_at or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        db = self._store._db
        await db.execute(
            """
            INSERT INTO bypass_events (pattern, occurred_at, kind, session_id, ci_detected)
            VALUES (?, ?, 'inline', ?, 0)
            """,
            (cmd, now_iso, session_id),
        )
        await db.commit()

        # Check auto-learn and active-reinforce in background
        await self._maybe_auto_learn(cmd, now)
        await self._maybe_reinforce(cmd, session_id, datetime.now(timezone.utc).isoformat())

    async def record_inherited_bypass(
        self,
        cmd: str,
        session_id: str,
    ) -> None:
        """Record that an inherited NO_COMPRESS=1 bypass occurred (no-op for storage).

        Inherited bypasses do NOT count toward auto-learn; they are passed
        through silently. This method exists so callers can make intent clear.
        """
        # D5c: inherited env bypass is not recorded — nothing to do.
        pass

    async def record_passive_reinforcement(
        self,
        cmd: str,
        session_id: str,
    ) -> None:
        """Record passive reinforcement — bypass rule fired silently.

        Updates last_reinforced_at and session_count for any active rule
        that matches this command.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._maybe_reinforce(cmd, session_id, now_iso)

    async def record_non_reinforcement_session(
        self, cmd: str, session_id: str
    ) -> None:
        """Record a session that ran WITHOUT reinforcing the bypass for cmd.

        Used for decay tracking: session_count increments here for sessions
        that did NOT issue NO_COMPRESS for this pattern.
        """
        db = self._store._db
        # Find a matching active learned rule for this command
        pattern = await self._find_matching_rule_pattern(cmd)
        if pattern is None:
            return

        await db.execute(
            """
            UPDATE bypass_rules
            SET session_count = session_count + 1
            WHERE pattern = ? AND source = 'learned'
            """,
            (pattern,),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def is_bypassed(self, cmd: str) -> bool:
        """Return True if there is an active bypass rule matching cmd.

        Checks bypass_rules for any row where the rule's pattern is a prefix
        of cmd's argv and is_active=1.
        """
        db = self._store._db
        async with db.execute(
            "SELECT pattern FROM bypass_rules WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()

        for (pattern,) in rows:
            if _cmd_matches_pattern(cmd, pattern):
                return True
        return False

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    async def check_and_decay(self, cmd: str) -> None:
        """Expire learned bypass rules that have exceeded decay thresholds.

        Only learned rules decay; manual rules are immune.
        Thresholds: 20 non-reinforcing sessions OR 90 calendar days since
        last reinforcement.
        """
        now = datetime.now(timezone.utc)
        db = self._store._db
        pattern = await self._find_matching_rule_pattern(cmd)
        if pattern is None:
            return

        async with db.execute(
            "SELECT session_count, last_reinforced_at, source, is_active FROM bypass_rules WHERE pattern = ?",
            (pattern,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return

        session_count, last_reinforced_iso, source, is_active = (
            row[0], row[1], row[2], row[3]
        )
        if source == "manual":
            return  # manual rules never decay

        if not is_active:
            return  # already decayed

        # Parse last_reinforced_at
        try:
            last_reinforced = datetime.fromisoformat(last_reinforced_iso)
            if last_reinforced.tzinfo is None:
                last_reinforced = last_reinforced.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            last_reinforced = now

        should_decay = _should_decay(session_count, last_reinforced, now)
        if should_decay:
            await db.execute(
                "UPDATE bypass_rules SET is_active = 0 WHERE pattern = ?",
                (pattern,),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _maybe_auto_learn(self, cmd: str, now: datetime) -> None:  # noqa: ARG002
        """Check if the auto-learn threshold is reached and create a rule if so.

        The 14-day window is always computed from real wall-clock time so that
        events recorded with backdated occurred_at are evaluated correctly.
        """
        db = self._store._db
        real_now = datetime.now(timezone.utc)
        window_start = (real_now - timedelta(days=_AUTO_LEARN_WINDOW_DAYS)).isoformat()

        # Get all inline events for commands that share a common argv prefix
        async with db.execute(
            "SELECT pattern FROM bypass_events WHERE kind = 'inline' AND occurred_at >= ?",
            (window_start,),
        ) as cursor:
            rows = await cursor.fetchall()
        all_cmds = [r[0] for r in rows]

        # Group commands by common prefix with current cmd
        prefix = _most_specific_prefix([cmd] + all_cmds)
        if not prefix:
            return

        # Count events where each event's cmd starts with this prefix
        matching = [c for c in all_cmds if _cmd_matches_pattern(c, prefix)]

        if len(matching) < _AUTO_LEARN_THRESHOLD:
            return

        # Check no rule already exists for this pattern
        async with db.execute(
            "SELECT pattern FROM bypass_rules WHERE pattern = ?",
            (prefix,),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            return

        now_iso = now.isoformat()
        await db.execute(
            """
            INSERT INTO bypass_rules (pattern, source, created_at, last_reinforced_at, session_count, is_active)
            VALUES (?, 'learned', ?, ?, 0, 1)
            """,
            (prefix, now_iso, now_iso),
        )
        await db.commit()

    async def _maybe_reinforce(
        self, cmd: str, session_id: str, now_iso: str
    ) -> None:
        """Update last_reinforced_at + session_count for any matching active rule."""
        db = self._store._db
        pattern = await self._find_matching_rule_pattern(cmd)
        if pattern is None:
            return

        await db.execute(
            """
            UPDATE bypass_rules
            SET last_reinforced_at = ?, session_count = session_count + 1
            WHERE pattern = ? AND is_active = 1
            """,
            (now_iso, pattern),
        )
        await db.commit()

    async def _find_matching_rule_pattern(self, cmd: str) -> str | None:
        """Find the pattern of the first active rule matching cmd, or None."""
        db = self._store._db
        async with db.execute(
            "SELECT pattern FROM bypass_rules WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()

        for (pattern,) in rows:
            if _cmd_matches_pattern(cmd, pattern):
                return pattern
        return None


def _should_decay(
    session_count: int,
    last_reinforced: datetime,
    now: datetime,
) -> bool:
    """Pure function: return True if a learned bypass rule should be decayed.

    Args:
        session_count: Number of non-reinforcing sessions since last reinforcement.
        last_reinforced: Datetime of last reinforcement.
        now: Current datetime (for calendar comparison).

    Returns:
        True if either threshold is exceeded.
    """
    if session_count >= _DECAY_SESSION_THRESHOLD:
        return True
    age_days = (now - last_reinforced).days
    if age_days >= _DECAY_CALENDAR_DAYS:
        return True
    return False
