"""Prompt templates for intent extraction."""

from __future__ import annotations

import json
from typing import Any

INTENT_JSON_SCHEMA: dict[str, Any] = {
    "hard_constraints": {
        "city": "string | null — city name, normalised e.g. bengaluru",
        "locality": "string | null — neighbourhood/area e.g. indiranagar, mg road",
        "is_veg": "boolean | null — true for vegetarian, false for non-vegetarian",
        "max_cost_for_two": "integer | null — max budget in INR for two people",
        "min_rating": "number | null — minimum rating 0.0–5.0",
        "cuisines": "array of strings — e.g. ['Chinese', 'North Indian']",
        "open_now": "boolean | null — true when user wants currently open places",
        "has_online_delivery": "boolean | null",
        "has_table_booking": "boolean | null",
        "max_price_range": "integer | null — 1 (cheap) to 4 (expensive)",
    },
    "soft_preferences": "array of strings — subjective terms e.g. cozy, romantic, rooftop",
}

INTENT_SYSTEM_PROMPT = """You extract restaurant search intent from natural language.

Separate HARD constraints (must filter the dataset) from SOFT preferences (subjective ranking only).

Hard constraint rules:
- Map colloquial budget terms: "cheap"/"budget" → max_price_range 1 or max_cost_for_two ~500–800;
  "under 1k"/"Rs. 800" → numeric max_cost_for_two; "budget no concern"/"no budget limit" → omit max_cost_for_two.
- Map diet: "vegetarian"/"veg" → is_veg true; "non-veg"/"non vegetarian" → is_veg false.
- Map "open now"/"open right now"/"currently open" → open_now true.
- Map delivery/booking requests to has_online_delivery / has_table_booking booleans.
- Extract city and locality from phrases like "near Indiranagar", "in MG Road", "Bengaluru".
  Normalise city aliases: Bangalore/Bengaluru → bengaluru. Use lowercase for city and locality.
- Put cuisine names in hard_constraints.cuisines when explicitly requested.
- Do NOT invent restaurants, IDs, or locations not implied by the query.
- Use null for unknown hard constraint fields. Use [] for empty cuisines or soft_preferences.

Soft preferences:
- Subjective ambiance, occasion, or vibe terms NOT already enforced as hard filters
  (e.g. cozy, romantic, date-night, rooftop, good for groups, quiet, street food).

Return ONLY valid JSON matching this schema:
{schema}
"""

INTENT_USER_PROMPT = """Query: "{query}"
Explicit filters (override parsed values for the same fields): {filters_json}

Return JSON with "hard_constraints" and "soft_preferences" keys only."""


def build_intent_system_prompt() -> str:
    """Format the system prompt with the JSON schema."""
    schema_text = json.dumps(INTENT_JSON_SCHEMA, indent=2)
    return INTENT_SYSTEM_PROMPT.format(schema=schema_text)


def build_intent_user_prompt(query: str, filters: dict[str, Any]) -> str:
    """Format the user prompt with query and explicit filters."""
    filters_json = json.dumps(filters or {}, ensure_ascii=False)
    return INTENT_USER_PROMPT.format(query=query, filters_json=filters_json)
