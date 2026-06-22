"""Deterministic candidate retrieval with pre-ranking and constraint relaxation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.data.loader import RestaurantStore
from app.data.models import HardConstraints, QueryIntent, Restaurant
from app.retrieval.filters import apply_hard_constraints
from app.retrieval.relaxation import RelaxationPolicy


class RetrievalResult(BaseModel):
    """Output of the deterministic retrieval layer."""

    candidates: list[Restaurant]
    applied_constraints: HardConstraints
    relaxed_constraints: list[str] = Field(default_factory=list)
    total_before_limit: int = 0


def pre_rank(restaurants: list[Restaurant]) -> list[Restaurant]:
    """Deterministic ordering: rating desc, then votes desc, then restaurant_id."""
    return sorted(
        restaurants,
        key=lambda r: (-r.rating, -r.votes, r.restaurant_id),
    )


class Retriever:
    """Filter restaurants on hard constraints and return a bounded shortlist."""

    def __init__(
        self,
        store: RestaurantStore,
        *,
        timezone: str = "Asia/Kolkata",
        relaxation_policy: RelaxationPolicy | None = None,
    ) -> None:
        self._store = store
        self._timezone = timezone
        self._relaxation_policy = relaxation_policy or RelaxationPolicy()

    def _filter(
        self,
        constraints: HardConstraints,
        *,
        now: datetime | None = None,
    ) -> list[Restaurant]:
        hc = constraints
        return apply_hard_constraints(
            self._store.get_all(),
            city=hc.city,
            locality=hc.locality,
            cuisines=hc.cuisines or None,
            is_veg=hc.is_veg,
            max_cost_for_two=hc.max_cost_for_two,
            min_rating=hc.min_rating,
            has_table_booking=hc.has_table_booking,
            has_online_delivery=hc.has_online_delivery,
            max_price_range=hc.max_price_range,
            open_now=hc.open_now,
            now=now,
            timezone=self._timezone,
        )

    def retrieve_candidates(
        self,
        intent: QueryIntent,
        *,
        max_candidates: int = 50,
        now: datetime | None = None,
    ) -> RetrievalResult:
        """Apply hard constraints, relax on zero matches, pre-rank, and cap."""
        self._relaxation_policy.reset()
        constraints = intent.hard_constraints.model_copy(deep=True)
        relaxed_notes: list[str] = []
        candidates = self._filter(constraints, now=now)
        max_steps = 20

        while not candidates and max_steps > 0:
            max_steps -= 1
            relaxed, note = self._relaxation_policy.relax_once(constraints)
            if note is None:
                break
            relaxed_notes.append(note)
            constraints = relaxed
            candidates = self._filter(constraints, now=now)

        ranked = pre_rank(candidates)
        total_before_limit = len(ranked)
        capped = ranked[:max_candidates]

        return RetrievalResult(
            candidates=capped,
            applied_constraints=constraints,
            relaxed_constraints=relaxed_notes,
            total_before_limit=total_before_limit,
        )


def constraints_to_dict(constraints: HardConstraints) -> dict[str, Any]:
    """Serialize only non-null constraint fields."""
    return constraints.model_dump(exclude_none=True)
