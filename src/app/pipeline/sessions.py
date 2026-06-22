"""In-memory conversation session store (Phase 9.3).

Tracks per-session context so users can refine results across turns
("show cheaper options", "something with outdoor seating"). Bounded by TTL and
size; no external store required for the MVP (swap for Redis at scale).
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    """Accumulated context for one conversation."""

    hard_constraints: dict[str, Any] = field(default_factory=dict)
    soft_preferences: list[str] = field(default_factory=list)
    shown_ids: list[str] = field(default_factory=list)
    turns: int = 0


class SessionStore:
    """TTL + LRU bounded session store."""

    def __init__(self, *, ttl_seconds: int = 1800, max_entries: int = 512) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: "OrderedDict[str, tuple[float, SessionState]]" = OrderedDict()

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now >= exp]
        for k in expired:
            self._store.pop(k, None)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def get(self, session_id: str) -> SessionState | None:
        entry = self._store.get(session_id)
        if entry is None:
            return None
        expires_at, state = entry
        if time.monotonic() >= expires_at:
            self._store.pop(session_id, None)
            return None
        self._store.move_to_end(session_id)
        return state

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState]:
        """Return an existing session or create a fresh one with a new id."""
        if session_id:
            state = self.get(session_id)
            if state is not None:
                return session_id, state
        new_id = session_id or uuid.uuid4().hex[:16]
        state = SessionState()
        self.save(new_id, state)
        return new_id, state

    def save(self, session_id: str, state: SessionState) -> None:
        self._prune()
        self._store[session_id] = (time.monotonic() + self._ttl, state)
        self._store.move_to_end(session_id)

    def clear(self) -> None:
        self._store.clear()
