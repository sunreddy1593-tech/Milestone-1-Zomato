"""Deterministic fallback ranker — used when Groq is unavailable or fails."""

from __future__ import annotations

from app.data.models import Restaurant


def _normalise_rating(rating: float) -> float:
    return max(0.0, min(rating, 5.0)) / 5.0


def _tag_overlap(ambiance_tags: list[str], soft_preferences: list[str]) -> float:
    if not soft_preferences:
        return 0.0
    tags = {t.lower() for t in ambiance_tags}
    prefs = {p.lower() for p in soft_preferences}
    if not tags:
        return 0.0
    matches = sum(
        1
        for p in prefs
        if p in tags or any(p in t or t in p for t in tags)
    )
    return matches / len(prefs)


def _price_label(price_range: int) -> str:
    return {1: "budget-friendly", 2: "moderately priced", 3: "premium", 4: "fine-dining"}.get(
        price_range, "moderately priced"
    )


def _build_reason(
    restaurant: Restaurant,
    soft_preferences: list[str],
    matched_tags: list[str],
) -> str:
    cuisine = ", ".join(restaurant.cuisines[:2]) if restaurant.cuisines else "varied"
    price = _price_label(restaurant.price_range)
    parts = [
        f"Rated {restaurant.rating}/5 ({restaurant.votes} votes), "
        f"{price} {cuisine} option in {restaurant.locality.title()}"
    ]
    if matched_tags:
        parts.append(f"matching your preference for {', '.join(matched_tags)}")
    return ". ".join(parts) + "."


def fallback_rank(
    candidates: list[Restaurant],
    *,
    soft_preferences: list[str],
    top_n: int,
    rating_weight: float = 0.6,
    tag_weight: float = 0.4,
) -> list[dict]:
    """Score candidates deterministically and return top-N ranking dicts.

    score = rating_weight * normalized_rating + tag_weight * tag_overlap
    """
    scored: list[tuple[float, Restaurant, list[str]]] = []
    prefs_lower = {p.lower() for p in soft_preferences}

    for r in candidates:
        rating_component = _normalise_rating(r.rating)
        overlap = _tag_overlap(r.ambiance_tags, soft_preferences)
        score = rating_weight * rating_component + tag_weight * overlap
        matched = [
            t
            for t in r.ambiance_tags
            if t.lower() in prefs_lower
            or any(p in t.lower() or t.lower() in p for p in prefs_lower)
        ]
        scored.append((score, r, matched))

    scored.sort(key=lambda x: (-x[0], -x[1].rating, -x[1].votes, x[1].restaurant_id))

    rankings: list[dict] = []
    for idx, (score, restaurant, matched) in enumerate(scored[:top_n], start=1):
        rankings.append(
            {
                "restaurant_id": restaurant.restaurant_id,
                "match_score": round(score, 4),
                "rank": idx,
                "reason": _build_reason(restaurant, soft_preferences, matched),
            }
        )
    return rankings
