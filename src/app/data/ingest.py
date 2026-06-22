"""Zomato HuggingFace dataset ingestion & preprocessing.

Downloads the dataset from
https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation,
transforms each raw row into the canonical ``Restaurant`` schema, and writes
the result to ``data/restaurants.json``.

Run standalone:
    python -m app.data.ingest            (from src/ directory)

Or import and call ``ingest()`` programmatically.

Dependencies (add to requirements.txt if not present):
    datasets          — HuggingFace datasets library for downloading
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"
DEFAULT_CITY = "bengaluru"  # All Zomato Bangalore data → normalised
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "restaurants.json"

# Non-veg cuisine keywords (used to infer is_veg when not explicit)
_NONVEG_CUISINES = {
    "seafood", "bbq", "steak", "grill", "sushi", "pork",
    "barbeque", "barbecue",
}

# Ambiance keywords to extract from rest_type / listed_in(type)
_REST_TYPE_AMBIANCE_MAP: dict[str, list[str]] = {
    "fine dining": ["fine dining", "upscale", "premium"],
    "casual dining": ["casual", "relaxed"],
    "cafe": ["cafe", "coffee", "cozy"],
    "quick bites": ["quick bites", "fast food"],
    "bar": ["bar", "nightlife", "drinks"],
    "pub": ["pub", "nightlife", "drinks"],
    "lounge": ["lounge", "chill", "relaxed"],
    "bakery": ["bakery", "pastries"],
    "dessert parlor": ["desserts", "sweet"],
    "dessert parlour": ["desserts", "sweet"],
    "food court": ["food court"],
    "sweet shop": ["sweets", "traditional"],
    "dhaba": ["dhaba", "rustic", "traditional"],
    "kiosk": ["quick bites", "takeaway"],
    "microbrewery": ["microbrewery", "craft beer", "nightlife"],
    "club": ["club", "nightlife", "party"],
    "buffet": ["buffet", "unlimited"],
    "delivery": ["delivery"],
    "takeaway": ["takeaway"],
    "mess": ["mess", "homestyle"],
    "food truck": ["food truck", "street food"],
    "irani cafe": ["irani cafe", "traditional", "cozy"],
    "bhojanalya": ["traditional", "homestyle"],
    "confectionery": ["confectionery", "sweets"],
}

# Cuisine keywords suggesting vegetarian-only
_VEG_CUISINE_KEYWORDS = {
    "south indian", "north indian", "rajasthani", "gujarati",
    "mithai", "bakery", "desserts", "beverages", "juices",
    "ice cream", "cafe", "salad", "vegan",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_rate(raw: Any) -> float:
    """Parse '4.1/5', 'NEW', '-', or None into a float 0.0–5.0."""
    if not raw or not isinstance(raw, str):
        return 0.0
    raw = raw.strip()
    m = re.match(r"(\d+\.?\d*)\s*/\s*5", raw)
    if m:
        return min(float(m.group(1)), 5.0)
    return 0.0


def _clean_cost(raw: Any) -> int:
    """Parse cost string ('800', '1,200', None) → int."""
    if not raw:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    cleaned = re.sub(r"[^\d]", "", str(raw))
    return int(cleaned) if cleaned else 0


def _cost_to_price_range(cost: int) -> int:
    """Map average_cost_for_two to 1–4 price_range."""
    if cost <= 300:
        return 1
    if cost <= 800:
        return 2
    if cost <= 1500:
        return 3
    return 4


def _split_csv(raw: Any) -> list[str]:
    """Split comma-separated string into trimmed, non-empty items."""
    if not raw or not isinstance(raw, str):
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _yes_no_to_bool(raw: Any) -> bool:
    """Convert 'Yes'/'No' strings to bool."""
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "yes" if raw else False


def _infer_is_veg(cuisines: list[str], dish_liked: list[str]) -> str:
    """Heuristic: infer Veg / Non-Veg / Both from cuisines & dishes.

    Returns 'Both' when uncertain — safe default.
    """
    cuisines_lower = {c.lower() for c in cuisines}
    dishes_lower = {d.lower() for d in dish_liked}

    has_nonveg_cuisine = bool(cuisines_lower & _NONVEG_CUISINES)

    nonveg_dish_keywords = {"chicken", "mutton", "fish", "prawn", "lamb",
                            "pork", "egg", "crab", "shrimp", "meat",
                            "keema", "gosht", "tikka", "kebab", "tandoori"}
    has_nonveg_dish = any(
        kw in d for d in dishes_lower for kw in nonveg_dish_keywords
    )

    if has_nonveg_cuisine or has_nonveg_dish:
        return "Non-Veg"

    # Check if explicitly vegetarian-sounding
    veg_only_keywords = {"pure veg", "jain", "vegan"}
    if cuisines_lower & veg_only_keywords:
        return "Veg"

    return "Both"


def _extract_ambiance_tags(
    rest_type_raw: str | None,
    listed_in_type: str | None,
) -> list[str]:
    """Derive ambiance_tags from restaurant type and listing type."""
    tags: set[str] = set()

    for raw in (rest_type_raw, listed_in_type):
        if not raw:
            continue
        for part in raw.split(","):
            key = part.strip().lower()
            if key in _REST_TYPE_AMBIANCE_MAP:
                tags.update(_REST_TYPE_AMBIANCE_MAP[key])
            elif key:
                tags.add(key)

    return sorted(tags)


def _generate_description(
    name: str,
    cuisines: list[str],
    rest_types: list[str],
    locality: str,
    rating: float,
    cost: int,
    popular_dishes: list[str],
) -> str:
    """Generate a short natural-language description for LLM consumption."""
    parts: list[str] = []

    # Opening
    cuisine_str = ", ".join(cuisines[:3]) if cuisines else "multi-cuisine"
    type_str = rest_types[0] if rest_types else "restaurant"
    parts.append(f"{name} is a {type_str.lower()} in {locality} serving {cuisine_str}.")

    # Rating + cost
    if rating > 0:
        parts.append(f"Rated {rating}/5")
        if cost > 0:
            parts.append(f"with an average cost of ₹{cost} for two.")
        else:
            parts.append(".")

    # Popular dishes
    if popular_dishes:
        dish_str = ", ".join(popular_dishes[:5])
        parts.append(f"Popular dishes include {dish_str}.")

    return " ".join(parts)


def _stable_id(name: str, address: str, idx: int) -> str:
    """Generate a stable, unique restaurant ID."""
    raw = f"{name}|{address}|{idx}"
    h = hashlib.md5(raw.encode()).hexdigest()[:6].upper()
    return f"R{idx:04d}_{h}"


def _generate_default_hours() -> dict[str, dict[str, str]]:
    """Return plausible default opening hours (11:00–23:00 daily).

    The raw Zomato dataset does not include opening_hours, so we
    provide reasonable defaults.  Phase 6 can refine this.
    """
    default = {"open": "11:00", "close": "23:00"}
    return {day: default for day in [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]}


# ---------------------------------------------------------------------------
# Main transform
# ---------------------------------------------------------------------------

def transform_row(row: dict[str, Any], idx: int) -> dict[str, Any]:
    """Transform a single raw Zomato row into the canonical Restaurant shape."""

    name = (row.get("name") or "").strip()
    address = (row.get("address") or "").strip()
    locality = (row.get("location") or "").strip()
    listed_in_city = (row.get("listed_in(city)") or "").strip()

    cuisines = _split_csv(row.get("cuisines"))
    dish_liked = _split_csv(row.get("dish_liked"))
    cost = _clean_cost(row.get("approx_cost(for two people)"))
    rating = _clean_rate(row.get("rate"))
    votes = int(row.get("votes") or 0)
    rest_type_raw = (row.get("rest_type") or "").strip()
    rest_types = _split_csv(rest_type_raw)
    listed_in_type = (row.get("listed_in(type)") or "").strip()

    return {
        "restaurant_id": _stable_id(name, address, idx),
        "name": name,
        "city": DEFAULT_CITY,
        "locality": locality.lower() if locality else listed_in_city.lower(),
        "cuisines": cuisines,
        "average_cost_for_two": cost,
        "price_range": _cost_to_price_range(cost),
        "rating": rating,
        "votes": votes,
        "is_veg": _infer_is_veg(cuisines, dish_liked),
        "has_table_booking": _yes_no_to_bool(row.get("book_table")),
        "has_online_delivery": _yes_no_to_bool(row.get("online_order")),
        "ambiance_tags": _extract_ambiance_tags(rest_type_raw, listed_in_type),
        "opening_hours": _generate_default_hours(),
        "latitude": None,
        "longitude": None,
        "popular_dishes": dish_liked[:10],  # cap at 10
        "description": _generate_description(
            name, cuisines, rest_types, locality or listed_in_city,
            rating, cost, dish_liked,
        ),
        # Extra Zomato fields
        "address": address,
        "phone": (row.get("phone") or "").strip(),
        "url": (row.get("url") or "").strip(),
        "rest_type": rest_types,
        "listed_in_type": listed_in_type,
        "listed_in_city": listed_in_city,
    }


def _deduplicate(records: list[dict]) -> list[dict]:
    """Remove duplicates by (name, locality) keeping highest-voted entry."""
    seen: dict[tuple[str, str], dict] = {}
    for rec in records:
        key = (rec["name"].lower(), rec["locality"])
        existing = seen.get(key)
        if existing is None or rec["votes"] > existing["votes"]:
            seen[key] = rec
    return list(seen.values())


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------

def ingest(
    output_path: Path = OUTPUT_PATH,
    *,
    max_records: int | None = None,
    deduplicate: bool = True,
) -> list[dict]:
    """Download, transform, deduplicate and write restaurants.json.

    Parameters
    ----------
    output_path:
        Where to write the final JSON file.
    max_records:
        Cap on total records (useful for testing). ``None`` = all.
    deduplicate:
        If True, keep only the highest-voted entry per (name, locality).

    Returns
    -------
    The list of transformed restaurant dicts that were written.
    """
    # --- Step 1: Load from HuggingFace ---
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        print(
            "ERROR: The 'datasets' package is required for ingestion.\n"
            "       Install it with:  pip install datasets\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Downloading dataset: {DATASET_ID} ...")
    ds = load_dataset(DATASET_ID, split="train")
    total_raw = len(ds)
    print(f"   -> {total_raw:,} raw rows loaded")

    # --- Step 2: Transform ---
    print("Transforming rows ...")
    records: list[dict] = []
    skipped = 0
    for idx, row in enumerate(ds):
        if max_records and idx >= max_records:
            break
        name = (row.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        records.append(transform_row(row, idx))

    print(f"   -> {len(records):,} records transformed, {skipped} skipped (no name)")

    # --- Step 3: Deduplicate ---
    if deduplicate:
        before = len(records)
        records = _deduplicate(records)
        print(f"Deduplicated: {before:,} -> {len(records):,} unique restaurants")

    # Re-assign sequential IDs after dedup for cleanliness
    for i, rec in enumerate(records):
        rec["restaurant_id"] = f"R{i+1:04d}"

    # --- Step 4: Write ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(records):,} restaurants to {output_path}")

    # --- Stats ---
    localities = {r["locality"] for r in records}
    cuisine_set: set[str] = set()
    for r in records:
        cuisine_set.update(r["cuisines"])
    veg_counts = {}
    for r in records:
        veg_counts[r["is_veg"]] = veg_counts.get(r["is_veg"], 0) + 1

    print(f"\nDataset Summary:")
    print(f"   Restaurants : {len(records):,}")
    print(f"   Localities  : {len(localities)}")
    print(f"   Cuisines    : {len(cuisine_set)}")
    print(f"   Veg split   : {veg_counts}")
    ratings = [r["rating"] for r in records if r["rating"] > 0]
    if ratings:
        print(f"   Rating range: {min(ratings):.1f} - {max(ratings):.1f} (avg {sum(ratings)/len(ratings):.2f})")
    costs = [r["average_cost_for_two"] for r in records if r["average_cost_for_two"] > 0]
    if costs:
        print(f"   Cost range  : Rs.{min(costs)} - Rs.{max(costs)} (avg Rs.{sum(costs)//len(costs)})")

    return records


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ingest()
