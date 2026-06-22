"""Restaurant data model and related schemas.

Defines the canonical `Restaurant` data model used throughout the system,
plus `QueryIntent` and `HardConstraints` schemas for later phases.

The Restaurant model maps the architecture's §7.1 entity schema, with
preprocessing logic to ingest the raw Zomato HuggingFace dataset into
this normalised form.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Opening hours
# ---------------------------------------------------------------------------

class DayHours(BaseModel):
    """Opening hours for a single day."""
    open: str = Field(..., description="Opening time in HH:MM 24-hour format")
    close: str = Field(..., description="Closing time in HH:MM 24-hour format")


# ---------------------------------------------------------------------------
# Restaurant entity — architecture §7.1
# ---------------------------------------------------------------------------

class Restaurant(BaseModel):
    """Canonical restaurant record used everywhere in the system.

    Fields map 1-to-1 with architecture §7.1.  The Zomato ingestion
    script transforms raw dataset rows into this shape.
    """

    restaurant_id: str = Field(..., description="Stable unique ID (e.g. R001)")
    name: str
    city: str = Field(..., description="Normalised to lowercase for matching")
    locality: str = Field(..., description="Neighbourhood / area")
    cuisines: list[str] = Field(default_factory=list)
    average_cost_for_two: int = Field(0, description="INR")
    price_range: int = Field(
        1, ge=1, le=4, description="1 = cheap … 4 = expensive"
    )
    rating: float = Field(0.0, ge=0.0, le=5.0)
    votes: int = 0
    is_veg: str = Field("Both", description="Veg | Non-Veg | Both")
    has_table_booking: bool = False
    has_online_delivery: bool = False
    ambiance_tags: list[str] = Field(default_factory=list)
    opening_hours: dict[str, DayHours] = Field(
        default_factory=dict,
        description="Per-weekday open/close; may be empty if unknown",
    )
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    popular_dishes: list[str] = Field(default_factory=list)
    description: str = ""

    # --- Extra Zomato-sourced fields (useful for UI / LLM) ---
    address: str = ""
    phone: str = ""
    url: str = ""
    rest_type: list[str] = Field(
        default_factory=list, description="e.g. Casual Dining, Cafe"
    )
    listed_in_type: str = ""
    listed_in_city: str = ""


# ---------------------------------------------------------------------------
# Query intent models — schemas for Phase 3+
# ---------------------------------------------------------------------------

class HardConstraints(BaseModel):
    """Structured hard constraints extracted from a user query."""

    city: Optional[str] = None
    locality: Optional[str] = None
    is_veg: Optional[bool] = None
    max_cost_for_two: Optional[int] = None
    min_rating: Optional[float] = None
    cuisines: list[str] = Field(default_factory=list)
    open_now: Optional[bool] = None
    has_online_delivery: Optional[bool] = None
    has_table_booking: Optional[bool] = None
    max_price_range: Optional[int] = None


class QueryIntent(BaseModel):
    """Structured intent parsed from NL query + explicit filters."""

    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: list[str] = Field(default_factory=list)
    original_query: str = ""
