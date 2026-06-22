"""Phase 4 — ranking, reasoning and fallback tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.data.models import DayHours, HardConstraints, QueryIntent, Restaurant
from app.llm.groq_client import GroqClientError
from app.ranking.fallback import fallback_rank
from app.ranking.ranker import Ranker
from app.utils.validation import (
    backfill_rankings,
    normalise_scores_and_ranks,
    validate_ranking_ids,
)


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """LLM stub returning a preset ranking payload or raising an error."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    async def complete_json(self, *args: Any, **kwargs: Any) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload if self.payload is not None else {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _hours() -> dict[str, DayHours]:
    day = DayHours(open="11:00", close="23:00")
    return {d: day for d in (
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    )}


@pytest.fixture
def candidates() -> list[Restaurant]:
    return [
        Restaurant(
            restaurant_id="R001",
            name="Cozy Corner",
            city="bengaluru",
            locality="indiranagar",
            cuisines=["North Indian", "Continental"],
            average_cost_for_two=1200,
            price_range=2,
            rating=4.5,
            votes=842,
            is_veg="Veg",
            ambiance_tags=["cozy", "romantic"],
            popular_dishes=["Paneer Tikka"],
            description="A cozy spot.",
            opening_hours=_hours(),
        ),
        Restaurant(
            restaurant_id="R002",
            name="Group Hub",
            city="bengaluru",
            locality="indiranagar",
            cuisines=["Chinese"],
            average_cost_for_two=800,
            price_range=2,
            rating=4.2,
            votes=512,
            is_veg="Both",
            ambiance_tags=["good for groups", "lively"],
            popular_dishes=["Noodles"],
            description="Great for groups.",
            opening_hours=_hours(),
        ),
        Restaurant(
            restaurant_id="R003",
            name="Plain Eatery",
            city="bengaluru",
            locality="indiranagar",
            cuisines=["South Indian"],
            average_cost_for_two=400,
            price_range=1,
            rating=3.9,
            votes=120,
            is_veg="Veg",
            ambiance_tags=[],
            popular_dishes=["Dosa"],
            description="Simple food.",
            opening_hours=_hours(),
        ),
    ]


@pytest.fixture
def intent() -> QueryIntent:
    return QueryIntent(
        original_query="cozy romantic place",
        hard_constraints=HardConstraints(city="bengaluru", locality="indiranagar"),
        soft_preferences=["cozy", "romantic"],
    )


# ---------------------------------------------------------------------------
# validate_ranking_ids
# ---------------------------------------------------------------------------


def test_validate_ranking_ids_strips_hallucinated() -> None:
    rankings = [
        {"restaurant_id": "R001", "match_score": 0.9},
        {"restaurant_id": "FAKE999", "match_score": 0.8},
        {"restaurant_id": "R002", "match_score": 0.7},
    ]
    valid = validate_ranking_ids(rankings, {"R001", "R002", "R003"})
    assert [e["restaurant_id"] for e in valid] == ["R001", "R002"]


def test_validate_ranking_ids_dedupes() -> None:
    rankings = [
        {"restaurant_id": "R001", "match_score": 0.9},
        {"restaurant_id": "R001", "match_score": 0.5},
    ]
    valid = validate_ranking_ids(rankings, {"R001"})
    assert len(valid) == 1


def test_backfill_rankings_pads_to_top_n() -> None:
    rankings = [{"restaurant_id": "R001", "match_score": 0.9}]
    result = backfill_rankings(rankings, ["R001", "R002", "R003"], top_n=3)
    assert [e["restaurant_id"] for e in result] == ["R001", "R002", "R003"]
    assert result[1]["backfilled"] is True


def test_normalise_scores_and_ranks_sorts_and_assigns() -> None:
    rankings = [
        {"restaurant_id": "R001", "match_score": 0.7},
        {"restaurant_id": "R002", "match_score": 0.9},
        {"restaurant_id": "R003", "match_score": None},
    ]
    ordered = normalise_scores_and_ranks(rankings)
    assert [e["restaurant_id"] for e in ordered] == ["R002", "R001", "R003"]
    assert [e["rank"] for e in ordered] == [1, 2, 3]


# ---------------------------------------------------------------------------
# fallback_rank
# ---------------------------------------------------------------------------


def test_fallback_rank_produces_valid_top_n(candidates: list[Restaurant]) -> None:
    rankings = fallback_rank(candidates, soft_preferences=["cozy", "romantic"], top_n=2)
    assert len(rankings) == 2
    for entry in rankings:
        assert entry["restaurant_id"] in {"R001", "R002", "R003"}
        assert entry["match_score"] is not None
        assert entry["reason"]
        assert "rank" in entry


def test_fallback_rank_prefers_tag_overlap(candidates: list[Restaurant]) -> None:
    rankings = fallback_rank(candidates, soft_preferences=["cozy", "romantic"], top_n=3)
    # R001 has both matching tags and highest rating → rank 1
    assert rankings[0]["restaurant_id"] == "R001"


def test_fallback_rank_without_preferences_uses_rating(
    candidates: list[Restaurant],
) -> None:
    rankings = fallback_rank(candidates, soft_preferences=[], top_n=3)
    assert rankings[0]["restaurant_id"] == "R001"
    assert rankings[-1]["restaurant_id"] == "R003"


# ---------------------------------------------------------------------------
# Ranker — Groq path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ranker_groq_path_returns_grounded_top_n(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    mock = MockLLMClient(
        payload={
            "rankings": [
                {"restaurant_id": "R001", "match_score": 0.92, "reason": "Cozy and romantic."},
                {"restaurant_id": "R002", "match_score": 0.75, "reason": "Good for groups."},
            ]
        }
    )
    ranker = Ranker(llm_client=mock)
    result = await ranker.rank(candidates, intent, top_n=2)

    assert result.ranker == "groq"
    assert len(result.recommendations) == 2
    ids = {r.restaurant_id for r in result.recommendations}
    assert ids <= {"R001", "R002", "R003"}
    for rec in result.recommendations:
        assert rec.match_score is not None
        assert rec.reason
        assert rec.rank >= 1


@pytest.mark.asyncio
async def test_ranker_strips_hallucinated_and_backfills(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    mock = MockLLMClient(
        payload={
            "rankings": [
                {"restaurant_id": "R001", "match_score": 0.92, "reason": "Cozy."},
                {"restaurant_id": "FAKE999", "match_score": 0.99, "reason": "Fake."},
            ]
        }
    )
    ranker = Ranker(llm_client=mock)
    result = await ranker.rank(candidates, intent, top_n=3)

    ids = [r.restaurant_id for r in result.recommendations]
    assert "FAKE999" not in ids
    assert len(result.recommendations) == 3  # backfilled to top_n
    assert all(r.restaurant_id in {"R001", "R002", "R003"} for r in result.recommendations)


@pytest.mark.asyncio
async def test_ranker_falls_back_on_groq_error(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    mock = MockLLMClient(error=GroqClientError("API down"))
    ranker = Ranker(llm_client=mock)
    result = await ranker.rank(candidates, intent, top_n=2)

    assert result.ranker == "fallback"
    assert len(result.recommendations) == 2
    assert result.recommendations[0].restaurant_id == "R001"


@pytest.mark.asyncio
async def test_ranker_falls_back_on_invalid_payload(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    mock = MockLLMClient(payload={"unexpected": "shape"})
    ranker = Ranker(llm_client=mock)
    result = await ranker.rank(candidates, intent, top_n=2)

    assert result.ranker == "fallback"
    assert len(result.recommendations) == 2


@pytest.mark.asyncio
async def test_ranker_all_hallucinated_uses_fallback(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    mock = MockLLMClient(
        payload={"rankings": [{"restaurant_id": "FAKE1"}, {"restaurant_id": "FAKE2"}]}
    )
    ranker = Ranker(llm_client=mock)
    result = await ranker.rank(candidates, intent, top_n=2)

    assert result.ranker == "fallback"
    assert all(r.restaurant_id in {"R001", "R002", "R003"} for r in result.recommendations)


@pytest.mark.asyncio
async def test_ranker_empty_candidates_returns_empty(intent: QueryIntent) -> None:
    ranker = Ranker(llm_client=MockLLMClient(payload={"rankings": []}))
    result = await ranker.rank([], intent, top_n=5)
    assert result.recommendations == []


@pytest.mark.asyncio
async def test_ranker_no_llm_uses_fallback(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    ranker = Ranker(llm_client=None)
    # No Groq key in CI → build_groq_client returns None → fallback
    if ranker._llm is not None:  # pragma: no cover - depends on env
        pytest.skip("Groq key present in environment")
    result = await ranker.rank(candidates, intent, top_n=3)
    assert result.ranker == "fallback"
    assert len(result.recommendations) == 3


@pytest.mark.asyncio
async def test_reasons_reference_real_attributes_smoke(
    candidates: list[Restaurant], intent: QueryIntent
) -> None:
    """Fallback reasons should mention real locality / rating values."""
    ranker = Ranker(llm_client=MockLLMClient(error=GroqClientError("force fallback")))
    result = await ranker.rank(candidates, intent, top_n=3)
    for rec in result.recommendations:
        assert rec.locality.title() in rec.reason
        assert str(rec.rating) in rec.reason
