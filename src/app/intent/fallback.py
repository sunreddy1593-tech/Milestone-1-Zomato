"""Rule-based intent parser — deterministic fallback when Groq is unavailable."""

from __future__ import annotations

import re

from app.data.models import HardConstraints, QueryIntent

_CITY_ALIASES = {
    "bangalore": "bengaluru",
    "bengaluru": "bengaluru",
    "bengaluru city": "bengaluru",
}

_VEG_PATTERNS = (
    r"\bvegetarian\b",
    r"\bveg\b(?!\s*non)",
    r"\bpure\s+veg\b",
    r"\bjain\b",
)
_NONVEG_PATTERNS = (
    r"\bnon[\s-]?veg\b",
    r"\bnon[\s-]?vegetarian\b",
)

_OPEN_NOW = re.compile(r"\bopen\s+(?:right\s+)?now\b|\bcurrently\s+open\b", re.I)
_DELIVERY = re.compile(r"\bonline\s+delivery\b|\bdelivery\b", re.I)
_BOOKING = re.compile(
    r"\btable\s+booking\b|\bbook(?:ing)?\s+(?:a\s+)?table\b", re.I
)
_NEAR = re.compile(
    r"\b(?:near|around|at|in)\s+([a-z0-9][a-z0-9\s\-']{1,40}?)"
    r"(?:\s*,|\s+that|\s+open|\s+under|\s+with|\s+for|\s*$|\.)",
    re.I,
)
_BUDGET_UNDER = re.compile(
    r"\b(?:under|below|less\s+than|<=?)\s*(?:rs\.?|₹)?\s*(\d+)\b", re.I
)
_BUDGET_FOR_TWO = re.compile(
    r"(?:rs\.?|₹)\s*(\d+)\s*(?:for\s+two|/\-?\s*two)", re.I
)
_NO_BUDGET = re.compile(
    r"\bbudget\s+no\s+concern\b|\bno\s+budget\b|\bprice\s+no\s+object\b", re.I
)
_CHEAP = re.compile(r"\b(?:cheap|budget(?:\s+friendly)?|affordable|low\s+cost)\b", re.I)
_MIN_RATING = re.compile(
    r"\b(?:min(?:imum)?\s+rating|rated?\s+(?:at\s+least|above|over))\s*(\d(?:\.\d)?)\b",
    re.I,
)
_BEST_RATED = re.compile(r"\bbest[\s-]?rated\b|\bhighest\s+rating\b", re.I)

_CUISINE_KEYWORDS = (
    "north indian",
    "south indian",
    "chinese",
    "thai",
    "italian",
    "continental",
    "mexican",
    "japanese",
    "korean",
    "american",
    "bbq",
    "street food",
    "cafe",
    "bakery",
    "desserts",
    "seafood",
    "maharashtrian",
    "bengali",
    "mughlai",
    "fast food",
)


def _normalise_location(value: str) -> str:
    return value.strip().lower()


def _extract_city(text: str) -> str | None:
    lower = text.lower()
    for alias, canonical in _CITY_ALIASES.items():
        if alias in lower:
            return canonical
    return None


def _extract_locality(text: str) -> str | None:
    match = _NEAR.search(text)
    if match:
        candidate = _normalise_location(match.group(1))
        if candidate in _CITY_ALIASES:
            return None
        return candidate
    return None


def _extract_cuisines(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for cuisine in _CUISINE_KEYWORDS:
        if cuisine in lower:
            found.append(cuisine.title() if " " not in cuisine else cuisine.title())
    return found


def _extract_soft_preferences(text: str, hard: HardConstraints) -> list[str]:
    lower = text.lower()
    soft: set[str] = set()

    keyword_map = {
        "cozy": r"\bcozy\b|\bcosy\b",
        "romantic": r"\bromantic\b|\bdate[\s-]?night\b|\banniversary\b",
        "rooftop": r"\brooftop\b",
        "family-friendly": r"\bfamily[\s-]?friendly\b",
        "good for groups": r"\bgood\s+for\s+groups\b|\blarge\s+groups\b",
        "quiet": r"\bquiet\b|\bpeaceful\b",
        "street food": r"\bstreet\s+food\b",
        "cheap": r"\b(?:cheap|budget(?:\s+friendly)?)\b",
        "coffee": r"\bgood\s+coffee\b|\bcoffee\b",
        "work-friendly": r"\b(?:work(?:ing)?|laptop)\b",
    }
    for label, pattern in keyword_map.items():
        if re.search(pattern, lower):
            soft.add(label)

    if "street food" in lower and "street food" not in (hard.cuisines or []):
        soft.add("street food")
    if _CHEAP.search(lower) and hard.max_cost_for_two is None:
        soft.add("cheap")

    return sorted(soft)


def rule_based_parse(query: str, *, default_city: str | None = None) -> QueryIntent:
    """Extract a best-effort ``QueryIntent`` using keyword and regex rules."""
    text = query.strip()
    lower = text.lower()
    hard = HardConstraints()

    if any(re.search(p, lower) for p in _NONVEG_PATTERNS):
        hard.is_veg = False
    elif any(re.search(p, lower) for p in _VEG_PATTERNS):
        hard.is_veg = True

    if _OPEN_NOW.search(text):
        hard.open_now = True
    if _DELIVERY.search(text):
        hard.has_online_delivery = True
    if _BOOKING.search(text):
        hard.has_table_booking = True

    city = _extract_city(text)
    locality = _extract_locality(text)
    if city:
        hard.city = city
    if locality:
        hard.locality = locality

    cuisines = _extract_cuisines(text)
    if cuisines:
        hard.cuisines = cuisines

    if _NO_BUDGET.search(text):
        pass
    elif match := _BUDGET_UNDER.search(text):
        hard.max_cost_for_two = int(match.group(1))
    elif match := _BUDGET_FOR_TWO.search(text):
        hard.max_cost_for_two = int(match.group(1))
    elif _CHEAP.search(text):
        hard.max_cost_for_two = 800
        hard.max_price_range = 1

    if match := _MIN_RATING.search(text):
        hard.min_rating = float(match.group(1))
    elif _BEST_RATED.search(text):
        hard.min_rating = 4.0

    if hard.city is None and hard.locality is None and default_city:
        hard.city = _normalise_location(default_city)

    soft = _extract_soft_preferences(text, hard)

    return QueryIntent(
        hard_constraints=hard,
        soft_preferences=soft,
        original_query=query,
    )
