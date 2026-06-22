"""In-memory TTL + LRU response cache (Phase 9.5).

Caches ``/recommend`` responses keyed by a normalised hash of the request.
Bounded in size (LRU eviction) and time (per-entry TTL). Cleared whenever the
dataset is reloaded so stale recommendations never outlive their data.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any


def make_cache_key(payload: dict[str, Any]) -> str:
    """Stable hash of a request payload (order-insensitive)."""
    normalised = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class ResponseCache:
    """Thread-unsafe (asyncio single-loop) TTL + LRU cache."""

    def __init__(self, *, ttl_seconds: int = 300, max_entries: int = 256) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            # Expired — drop it.
            self._store.pop(key, None)
            self.misses += 1
            return None
        self._store.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        if self._max <= 0:
            return
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict[str, int]:
        return {"size": len(self._store), "hits": self.hits, "misses": self.misses}
