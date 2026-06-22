"""Phase 9 — stretch feature tests (open-now, distance, semantic, cache,
conversational refinement, personalization)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.api.schemas import ChatRequest, RecommendRequest
from app.data.loader import RestaurantStore
from app.data.models import DayHours
from app.pipeline.cache import ResponseCache, make_cache_key
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.profiles import ProfileStore
from app.retrieval.semantic import SemanticIndex
from app.utils.geo import distance_for, haversine_km
from app.utils.hours import is_open_now

FIXTURE = "tests/fixtures/sample_restaurants.json"
IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Mock LLMs
# ---------------------------------------------------------------------------


class MockIntentLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def complete_json(self, *args: Any, **kwargs: Any) -> dict:
        return self.payload


class CountingRankingLLM:
    """Ranks candidate IDs found in the prompt; counts invocations."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema: dict, **kwargs: Any
    ) -> dict:
        import re

        self.calls += 1
        ids = re.findall(r'"restaurant_id":\s*"([^"]+)"', user_prompt)
        return {
            "rankings": [
                {"restaurant_id": rid, "match_score": round(0.95 - i * 0.1, 2), "reason": "Good fit."}
                for i, rid in enumerate(ids[:10])
            ]
        }


@pytest.fixture
def store() -> RestaurantStore:
    return RestaurantStore.from_file(FIXTURE)


def make_orchestrator(store: RestaurantStore, *, intent_payload=None, ranker_llm=None, **kw):
    return Orchestrator(
        store,
        intent_llm=MockIntentLLM(intent_payload) if intent_payload is not None else None,
        ranking_llm=ranker_llm,
        **kw,
    )


# ---------------------------------------------------------------------------
# 9.1 — Open now
# ---------------------------------------------------------------------------


def test_open_now_basic_window() -> None:
    oh = {"monday": DayHours(open="11:00", close="23:00")}
    assert is_open_now(oh, now=datetime(2026, 6, 15, 12, 0, tzinfo=IST)) is True  # Monday
    assert is_open_now(oh, now=datetime(2026, 6, 15, 23, 30, tzinfo=IST)) is False


def test_open_now_overnight_spill() -> None:
    oh = {"friday": DayHours(open="18:00", close="02:00")}
    # Saturday 01:00 — still open from Friday's overnight window.
    assert is_open_now(oh, now=datetime(2026, 6, 20, 1, 0, tzinfo=IST)) is True
    # Saturday 03:00 — closed.
    assert is_open_now(oh, now=datetime(2026, 6, 20, 3, 0, tzinfo=IST)) is False


def test_open_now_empty_hours_closed() -> None:
    assert is_open_now({}, now=datetime(2026, 6, 15, 12, 0, tzinfo=IST)) is False


# ---------------------------------------------------------------------------
# 9.2 — Distance
# ---------------------------------------------------------------------------


def test_haversine_known_distance() -> None:
    # ~1 degree of latitude ≈ 111 km.
    d = haversine_km(12.0, 77.0, 13.0, 77.0)
    assert 110 < d < 112


def test_distance_for_requires_all_coords() -> None:
    assert distance_for(12.9, 77.6, None, None) is None
    assert distance_for(None, None, 12.9, 77.6) is None
    assert distance_for(12.9784, 77.6408, 12.9784, 77.6408) == 0.0


@pytest.mark.asyncio
async def test_distance_attached_to_recommendations(store: RestaurantStore) -> None:
    orch = make_orchestrator(
        store,
        intent_payload={"hard_constraints": {"city": "bengaluru"}, "soft_preferences": []},
        ranker_llm=CountingRankingLLM(),
    )
    resp = await orch.recommend(
        RecommendRequest(query="dinner", top_n=3, user_lat=12.97, user_lng=77.64)
    )
    by_id = {r.restaurant_id: r for r in resp.recommendations}
    # R001 has coordinates → distance computed; R002 has none → distance None.
    assert by_id["R001"].distance_km is not None
    assert by_id["R002"].distance_km is None


# ---------------------------------------------------------------------------
# 9.4 — Semantic search
# ---------------------------------------------------------------------------


def test_semantic_ranks_relevant_higher(store: RestaurantStore) -> None:
    idx = SemanticIndex(store.get_all())
    scores = idx.score("rooftop romantic fine dining steak", ["R001", "R002", "R003"])
    assert scores["R003"] > scores["R002"]


def test_semantic_empty_query_zero(store: RestaurantStore) -> None:
    idx = SemanticIndex(store.get_all())
    scores = idx.score("", ["R001", "R002"])
    assert scores == {"R001": 0.0, "R002": 0.0}


# ---------------------------------------------------------------------------
# 9.5 — Caching
# ---------------------------------------------------------------------------


def test_cache_lru_eviction() -> None:
    c = ResponseCache(ttl_seconds=100, max_entries=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # touch a → b becomes LRU
    c.set("c", 3)  # evicts b
    assert c.get("b") is None
    assert c.get("a") == 1
    assert c.get("c") == 3


def test_cache_ttl_expiry() -> None:
    c = ResponseCache(ttl_seconds=0, max_entries=8)
    c.set("k", "v")
    assert c.get("k") is None  # already expired


def test_cache_key_order_insensitive() -> None:
    k1 = make_cache_key({"a": 1, "b": 2})
    k2 = make_cache_key({"b": 2, "a": 1})
    assert k1 == k2


@pytest.mark.asyncio
async def test_orchestrator_cache_hit_skips_ranker(store: RestaurantStore) -> None:
    ranker = CountingRankingLLM()
    orch = make_orchestrator(
        store,
        intent_payload={"hard_constraints": {"city": "bengaluru"}, "soft_preferences": ["cozy"]},
        ranker_llm=ranker,
    )
    req = RecommendRequest(query="cozy spot", top_n=3)
    first = await orch.recommend(req)
    second = await orch.recommend(req)

    assert first.meta.cached is False
    assert second.meta.cached is True
    assert ranker.calls == 1  # second served from cache


# ---------------------------------------------------------------------------
# 9.3 — Conversational refinement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_session_and_excludes_shown(store: RestaurantStore) -> None:
    orch = make_orchestrator(
        store,
        intent_payload={"hard_constraints": {"city": "bengaluru"}, "soft_preferences": []},
        ranker_llm=CountingRankingLLM(),
    )
    turn1 = await orch.recommend_chat(ChatRequest(query="places for dinner", top_n=2))
    assert turn1.session_id
    ids1 = {r.restaurant_id for r in turn1.recommendations}

    turn2 = await orch.recommend_chat(
        ChatRequest(session_id=turn1.session_id, query="more options", top_n=2)
    )
    ids2 = {r.restaurant_id for r in turn2.recommendations}
    # Previously shown restaurants are not repeated while new ones remain.
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_chat_cheaper_refinement(store: RestaurantStore) -> None:
    orch = make_orchestrator(
        store,
        intent_payload={"hard_constraints": {"city": "bengaluru"}, "soft_preferences": []},
        ranker_llm=CountingRankingLLM(),
    )
    turn1 = await orch.recommend_chat(ChatRequest(query="rooftop dinner", top_n=5))
    assert any(r.restaurant_id == "R003" for r in turn1.recommendations)  # premium present

    turn2 = await orch.recommend_chat(
        ChatRequest(session_id=turn1.session_id, query="show cheaper options", top_n=5)
    )
    assert turn2.query_understood.hard_constraints.get("max_price_range") == 2
    # The price-range-4 restaurant is filtered out by the cheaper refinement.
    assert all(r.restaurant_id != "R003" for r in turn2.recommendations)


# ---------------------------------------------------------------------------
# 9.6 — Personalization
# ---------------------------------------------------------------------------


def test_profile_store_learns_and_recommends() -> None:
    p = ProfileStore(top_k=2)
    p.observe("u1", cuisines=["Chinese", "Chinese", "Thai"], ambiance_tags=["cozy"])
    prefs = p.preferred("u1")
    assert "chinese" in prefs
    assert "cozy" in prefs
    assert p.preferred("unknown") == []


@pytest.mark.asyncio
async def test_personalization_injected_on_second_call(store: RestaurantStore) -> None:
    orch = make_orchestrator(
        store,
        intent_payload={"hard_constraints": {"city": "bengaluru"}, "soft_preferences": []},
        ranker_llm=CountingRankingLLM(),
        cache=ResponseCache(ttl_seconds=0, max_entries=0),  # disable caching for isolation
    )
    first = await orch.recommend(RecommendRequest(query="dinner one", top_n=3, user_id="u1"))
    second = await orch.recommend(RecommendRequest(query="dinner two", top_n=3, user_id="u1"))

    assert first.meta.personalized is False
    assert second.meta.personalized is True
