"""Geo helpers for distance-based ranking (Phase 9.2).

Pure-Python Haversine distance; no external dependencies. Restaurants in the
current dataset have no coordinates, so callers must treat distance as optional
and degrade gracefully when ``latitude``/``longitude`` are missing.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """Great-circle distance between two points in kilometres."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def distance_for(
    restaurant_lat: float | None,
    restaurant_lng: float | None,
    user_lat: float | None,
    user_lng: float | None,
) -> float | None:
    """Distance in km, or ``None`` when any coordinate is unavailable."""
    if (
        restaurant_lat is None
        or restaurant_lng is None
        or user_lat is None
        or user_lng is None
    ):
        return None
    return round(haversine_km(restaurant_lat, restaurant_lng, user_lat, user_lng), 3)
