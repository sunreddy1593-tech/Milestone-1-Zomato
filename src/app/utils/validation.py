"""Ranking validation helpers — enforce no-hallucination guarantees."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_ranking_ids(
    rankings: list[dict[str, Any]],
    candidate_ids: set[str],
) -> list[dict[str, Any]]:
    """Strip rankings whose ``restaurant_id`` is not in the candidate set.

    Also deduplicates by ``restaurant_id`` keeping the first (best-ranked)
    occurrence. Hallucinated or duplicate IDs are logged and dropped.
    """
    valid: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in rankings:
        rid = entry.get("restaurant_id")
        if rid is None:
            continue
        rid = str(rid)
        if rid not in candidate_ids:
            logger.warning("Dropping hallucinated restaurant_id from ranking: %s", rid)
            continue
        if rid in seen:
            logger.warning("Dropping duplicate restaurant_id from ranking: %s", rid)
            continue
        seen.add(rid)
        entry["restaurant_id"] = rid
        valid.append(entry)

    return valid


def backfill_rankings(
    rankings: list[dict[str, Any]],
    pre_ranked_ids: list[str],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Pad ``rankings`` up to ``top_n`` using deterministic pre-rank order.

    Backfilled entries get ``match_score=None`` and a templated reason placeholder
    (the caller enriches reasons with attributes).
    """
    present = {entry["restaurant_id"] for entry in rankings}
    result = list(rankings)

    for rid in pre_ranked_ids:
        if len(result) >= top_n:
            break
        if rid in present:
            continue
        result.append(
            {
                "restaurant_id": rid,
                "match_score": None,
                "reason": None,
                "backfilled": True,
            }
        )
        present.add(rid)

    return result[:top_n]


def normalise_scores_and_ranks(
    rankings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort by ``match_score`` desc (None last) and assign sequential ranks."""

    def sort_key(entry: dict[str, Any]) -> tuple[int, float]:
        score = entry.get("match_score")
        if score is None:
            return (1, 0.0)
        return (0, -float(score))

    ordered = sorted(rankings, key=sort_key)
    for idx, entry in enumerate(ordered, start=1):
        entry["rank"] = idx
    return ordered
