"""Pydantic request/response schemas for the API layer (architecture §9)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.ranking.ranker import Recommendation


class RecommendFilters(BaseModel):
    """Explicit structured filters that override LLM-parsed intent."""

    city: Optional[str] = None
    locality: Optional[str] = None
    cuisines: Optional[list[str]] = None
    is_veg: Optional[bool] = None
    max_cost_for_two: Optional[int] = Field(default=None, ge=0)
    min_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    has_table_booking: Optional[bool] = None
    has_online_delivery: Optional[bool] = None
    max_price_range: Optional[int] = Field(default=None, ge=1, le=4)
    open_now: Optional[bool] = None

    model_config = {"extra": "ignore"}


class RecommendRequest(BaseModel):
    """`POST /recommend` request body."""

    query: Optional[str] = Field(default=None, max_length=2000)
    filters: Optional[RecommendFilters] = None
    top_n: int = Field(default=5, ge=1, le=20)
    # Phase 9.2 — distance-based ranking (optional)
    user_lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    user_lng: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    max_distance_km: Optional[float] = Field(default=None, gt=0)
    # Phase 9.6 — personalization (optional)
    user_id: Optional[str] = Field(default=None, max_length=128)

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _require_query_or_filters(self) -> "RecommendRequest":
        has_query = bool(self.query and self.query.strip())
        has_filters = self.filters is not None and bool(
            self.filters.model_dump(exclude_none=True)
        )
        if not has_query and not has_filters:
            raise ValueError("At least one of query or filters is required")
        return self


class ChatRequest(BaseModel):
    """`POST /recommend/chat` request body — a single conversational turn."""

    session_id: Optional[str] = Field(default=None, max_length=64)
    query: Optional[str] = Field(default=None, max_length=2000)
    filters: Optional[RecommendFilters] = None
    top_n: int = Field(default=5, ge=1, le=20)
    user_lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    user_lng: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    user_id: Optional[str] = Field(default=None, max_length=128)

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _require_query_or_filters(self) -> "ChatRequest":
        has_query = bool(self.query and self.query.strip())
        has_filters = self.filters is not None and bool(
            self.filters.model_dump(exclude_none=True)
        )
        if not has_query and not has_filters:
            raise ValueError("At least one of query or filters is required")
        return self


class QueryUnderstood(BaseModel):
    """Echo of the final merged intent for transparency."""

    hard_constraints: dict[str, Any]
    soft_preferences: list[str]


class ResponseMeta(BaseModel):
    """Operational metadata about how the response was produced."""

    candidate_count: int
    latency_ms: int
    ranker: str
    groq_model: Optional[str] = None
    cached: bool = False
    used_semantic: bool = False
    personalized: bool = False


class RecommendResponse(BaseModel):
    """`POST /recommend` success response body (architecture §9.1)."""

    query_understood: QueryUnderstood
    recommendations: list[Recommendation]
    notes: Optional[str] = None
    meta: ResponseMeta
    session_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Generic error envelope."""

    error: str
    message: Optional[str] = None
    details: Optional[list[Any]] = None
