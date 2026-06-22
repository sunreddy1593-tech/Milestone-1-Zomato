"""Phase 7 — golden query regression tests (context §14).

Default mode is fully offline and deterministic:
  - intent parsing forced to the rule-based fallback (no network),
  - ranking uses a mock that echoes real candidate IDs.

Set ``RUN_LIVE_LLM_TESTS=1`` to additionally exercise the live Groq pipeline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from app.config import settings
from app.data.loader import RestaurantStore
from app.intent.parser import IntentParser
from app.llm.groq_client import GroqClientError
from app.pipeline.orchestrator import Orchestrator
from app.ranking.ranker import Ranker

FIXTURE = Path("tests/fixtures/sample_restaurants.json")

GOLDEN_QUERIES = [
    "Cheap vegetarian street food near MG Road, open right now.",
    "Romantic rooftop restaurant for an anniversary dinner, budget no concern.",
    "Family-friendly North Indian place that takes table bookings and seats large groups.",
    "Best-rated Chinese delivery under Rs.800 for two.",
    "A quiet cafe good for working with a laptop and good coffee.",
]


# ---------------------------------------------------------------------------
# Offline mocks
# ---------------------------------------------------------------------------


class FailingIntentLLM:
    """Forces the rule-based intent fallback (deterministic, offline)."""

    async def complete_json(self, *args: Any, **kwargs: Any) -> dict:
        raise GroqClientError("offline test — forcing rule-based parser")


class EchoRankingLLM:
    """Ranks the first N candidate IDs parsed from the prompt (offline)."""

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema: dict, **kwargs: Any
    ) -> dict:
        ids = re.findall(r'"restaurant_id":\s*"([^"]+)"', user_prompt)
        return {
            "rankings": [
                {"restaurant_id": rid, "match_score": 0.8, "reason": "Matches your request."}
                for rid in ids[:5]
            ]
        }


@pytest.fixture(scope="module")
def store() -> RestaurantStore:
    """Load the production dataset if present, else the small fixture."""
    if settings.data_file.exists():
        return RestaurantStore.from_file(settings.data_file)
    return RestaurantStore.from_file(FIXTURE)


@pytest.fixture
def orchestrator(store: RestaurantStore) -> Orchestrator:
    return Orchestrator(
        store,
        intent_parser=IntentParser(
            llm_client=FailingIntentLLM(), default_city="Bengaluru"
        ),
        ranker=Ranker(llm_client=EchoRankingLLM()),
    )


# ---------------------------------------------------------------------------
# Offline golden tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", GOLDEN_QUERIES)
@pytest.mark.asyncio
async def test_golden_query_is_grounded(
    query: str, orchestrator: Orchestrator, store: RestaurantStore
) -> None:
    from app.api.schemas import RecommendRequest

    response = await orchestrator.recommend(RecommendRequest(query=query, top_n=5))

    # No hallucination: every recommended ID exists in the dataset.
    for rec in response.recommendations:
        assert store.get_by_id(rec.restaurant_id) is not None
        assert rec.reason
        assert rec.rank >= 1

    assert len(response.recommendations) <= 5
    assert response.meta.candidate_count >= len(response.recommendations)


@pytest.mark.asyncio
async def test_golden_veg_query_respects_hard_constraint(
    orchestrator: Orchestrator, store: RestaurantStore
) -> None:
    from app.api.schemas import RecommendRequest

    response = await orchestrator.recommend(
        RecommendRequest(query=GOLDEN_QUERIES[0], top_n=5)
    )
    # "vegetarian" is a hard constraint and must never be relaxed away.
    for rec in response.recommendations:
        restaurant = store.get_by_id(rec.restaurant_id)
        assert restaurant is not None
        assert restaurant.is_veg in ("Veg", "Both")


@pytest.mark.asyncio
async def test_golden_delivery_query_respects_constraint(
    orchestrator: Orchestrator, store: RestaurantStore
) -> None:
    from app.api.schemas import RecommendRequest

    response = await orchestrator.recommend(
        RecommendRequest(query=GOLDEN_QUERIES[3], top_n=5)
    )
    if response.recommendations:
        for rec in response.recommendations:
            restaurant = store.get_by_id(rec.restaurant_id)
            assert restaurant is not None
            assert restaurant.has_online_delivery is True


# ---------------------------------------------------------------------------
# Live integration (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live Groq integration tests",
)
@pytest.mark.asyncio
async def test_live_groq_pipeline_grounded(store: RestaurantStore) -> None:
    from app.api.schemas import RecommendRequest

    orchestrator = Orchestrator(store)  # real Groq clients from settings
    response = await orchestrator.recommend(
        RecommendRequest(query=GOLDEN_QUERIES[0], top_n=5)
    )
    assert response.meta.ranker in ("groq", "fallback")
    for rec in response.recommendations:
        assert store.get_by_id(rec.restaurant_id) is not None
