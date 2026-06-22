"""Lightweight in-memory personalization profiles (Phase 9.6).

Learns a user's affinity for cuisines and ambiance tags from the
recommendations they receive, then injects the strongest learned preferences
into future queries as additional soft preferences. Bounded by size; opt-in via
an optional ``user_id`` on the request.
"""

from __future__ import annotations

from collections import Counter, OrderedDict


class ProfileStore:
    """Per-user preference counters (cuisines + ambiance tags)."""

    def __init__(self, *, max_users: int = 1000, top_k: int = 3) -> None:
        self._max = max_users
        self._top_k = top_k
        self._cuisines: "OrderedDict[str, Counter[str]]" = OrderedDict()
        self._ambiance: "OrderedDict[str, Counter[str]]" = OrderedDict()

    def _touch(self, user_id: str) -> None:
        if user_id not in self._cuisines:
            self._cuisines[user_id] = Counter()
            self._ambiance[user_id] = Counter()
        self._cuisines.move_to_end(user_id)
        self._ambiance.move_to_end(user_id)
        while len(self._cuisines) > self._max:
            old, _ = self._cuisines.popitem(last=False)
            self._ambiance.pop(old, None)

    def observe(
        self,
        user_id: str,
        *,
        cuisines: list[str],
        ambiance_tags: list[str],
    ) -> None:
        """Record cuisines/ambiance from a set of returned recommendations."""
        if not user_id:
            return
        self._touch(user_id)
        self._cuisines[user_id].update(c.lower() for c in cuisines if c)
        self._ambiance[user_id].update(t.lower() for t in ambiance_tags if t)

    def preferred(self, user_id: str) -> list[str]:
        """Return the user's strongest learned soft preferences."""
        if not user_id or user_id not in self._cuisines:
            return []
        prefs: list[str] = []
        for term, _ in self._ambiance[user_id].most_common(self._top_k):
            prefs.append(term)
        for term, _ in self._cuisines[user_id].most_common(self._top_k):
            prefs.append(term)
        return prefs

    def clear(self) -> None:
        self._cuisines.clear()
        self._ambiance.clear()
