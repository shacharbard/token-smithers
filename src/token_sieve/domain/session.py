"""Session state: SessionContext entity and InMemorySessionRepo.

SessionContext is a mutable entity tracking per-session dedup state.
InMemorySessionRepo is a dict-backed implementation of SessionRepository.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SessionContext:
    """Mutable entity tracking per-session compression state.

    Tracks seen content hashes for deduplication and result counts.
    """

    session_id: str
    seen_hashes: set[str] = field(default_factory=set)
    result_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_result_hash(self, content_hash: str) -> None:
        """Record a result hash. Skips if already seen (dedup)."""
        if content_hash not in self.seen_hashes:
            self.seen_hashes.add(content_hash)
            self.result_count += 1


DEFAULT_MAX_SESSIONS = 100


class InMemorySessionRepo:
    """Dict-backed session repository for Phase 1.

    Satisfies SessionRepository Protocol structurally.
    Evicts the oldest session (by created_at) when max_sessions is reached.
    """

    def __init__(self, max_sessions: int = DEFAULT_MAX_SESSIONS) -> None:
        self._store: dict[str, SessionContext] = {}
        self._max_sessions = max_sessions

    def get(self, session_id: str) -> SessionContext | None:
        """Retrieve a session by ID, or None if not found."""
        return self._store.get(session_id)

    def save(self, session: SessionContext) -> None:
        """Persist a session (overwrites if exists). Evicts oldest at cap."""
        if (
            session.session_id not in self._store
            and len(self._store) >= self._max_sessions
        ):
            oldest_id = min(
                self._store, key=lambda k: self._store[k].created_at
            )
            del self._store[oldest_id]
        self._store[session.session_id] = session
