"""Deterministic hard-constraint filters for restaurant retrieval."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher

from app.data.models import Restaurant
from app.utils.hours import is_open_now


def _normalise(value: str) -> str:
    return value.strip().lower()


def filter_by_city(restaurants: list[Restaurant], city: str) -> list[Restaurant]:
    """Case-insensitive city match."""
    city_norm = _normalise(city)
    return [r for r in restaurants if r.city == city_norm]


def _locality_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def filter_by_locality(
    restaurants: list[Restaurant],
    locality: str,
    *,
    fuzzy_threshold: float = 0.75,
) -> list[Restaurant]:
    """Exact match, then substring match, then fuzzy Levenshtein-like ratio."""
    loc_norm = _normalise(locality)

    exact = [r for r in restaurants if r.locality == loc_norm]
    if exact:
        return exact

    contains = [
        r
        for r in restaurants
        if loc_norm in r.locality or r.locality in loc_norm
    ]
    if contains:
        return contains

    fuzzy = [
        r
        for r in restaurants
        if _locality_similarity(loc_norm, r.locality) >= fuzzy_threshold
    ]
    return fuzzy


def filter_by_cuisines(
    restaurants: list[Restaurant], cuisines: list[str]
) -> list[Restaurant]:
    """Keep restaurants whose cuisines overlap any requested cuisine."""
    if not cuisines:
        return restaurants

    requested = {_normalise(c) for c in cuisines}
    return [
        r
        for r in restaurants
        if any(_normalise(c) in requested for c in r.cuisines)
        or any(
            any(req in _normalise(c) or _normalise(c) in req for req in requested)
            for c in r.cuisines
        )
    ]


def filter_by_veg(restaurants: list[Restaurant], is_veg: bool) -> list[Restaurant]:
    """``True`` → Veg or Both; ``False`` → Non-Veg or Both."""
    if is_veg:
        return [r for r in restaurants if r.is_veg in ("Veg", "Both")]
    return [r for r in restaurants if r.is_veg in ("Non-Veg", "Both")]


def filter_by_max_cost(
    restaurants: list[Restaurant], max_cost_for_two: int
) -> list[Restaurant]:
    """``average_cost_for_two <= max``."""
    return [r for r in restaurants if r.average_cost_for_two <= max_cost_for_two]


def filter_by_min_rating(
    restaurants: list[Restaurant], min_rating: float
) -> list[Restaurant]:
    """``rating >= min``."""
    return [r for r in restaurants if r.rating >= min_rating]


def filter_by_table_booking(
    restaurants: list[Restaurant], has_table_booking: bool
) -> list[Restaurant]:
    """Boolean equality on ``has_table_booking``."""
    return [r for r in restaurants if r.has_table_booking == has_table_booking]


def filter_by_delivery(
    restaurants: list[Restaurant], has_online_delivery: bool
) -> list[Restaurant]:
    """Boolean equality on ``has_online_delivery``."""
    return [r for r in restaurants if r.has_online_delivery == has_online_delivery]


def filter_by_price_range(
    restaurants: list[Restaurant], max_price_range: int
) -> list[Restaurant]:
    """``price_range <= max``."""
    return [r for r in restaurants if r.price_range <= max_price_range]


def filter_by_open_now(
    restaurants: list[Restaurant],
    *,
    open_now: bool,
    now: datetime | None = None,
    timezone: str = "Asia/Kolkata",
) -> list[Restaurant]:
    """Filter by whether the venue is open at ``now`` in ``timezone``."""
    if not open_now:
        return restaurants
    return [
        r
        for r in restaurants
        if is_open_now(r.opening_hours, now=now, timezone=timezone)
    ]


def apply_hard_constraints(
    restaurants: list[Restaurant],
    *,
    city: str | None = None,
    locality: str | None = None,
    cuisines: list[str] | None = None,
    is_veg: bool | None = None,
    max_cost_for_two: int | None = None,
    min_rating: float | None = None,
    has_table_booking: bool | None = None,
    has_online_delivery: bool | None = None,
    max_price_range: int | None = None,
    open_now: bool | None = None,
    now: datetime | None = None,
    timezone: str = "Asia/Kolkata",
) -> list[Restaurant]:
    """Apply all active hard constraints in deterministic order."""
    result = restaurants

    if city:
        result = filter_by_city(result, city)
    if locality:
        result = filter_by_locality(result, locality)
    if cuisines:
        result = filter_by_cuisines(result, cuisines)
    if is_veg is not None:
        result = filter_by_veg(result, is_veg)
    if max_cost_for_two is not None:
        result = filter_by_max_cost(result, max_cost_for_two)
    if min_rating is not None:
        result = filter_by_min_rating(result, min_rating)
    if has_table_booking is not None:
        result = filter_by_table_booking(result, has_table_booking)
    if has_online_delivery is not None:
        result = filter_by_delivery(result, has_online_delivery)
    if max_price_range is not None:
        result = filter_by_price_range(result, max_price_range)
    if open_now:
        result = filter_by_open_now(
            result, open_now=True, now=now, timezone=timezone
        )

    return result
