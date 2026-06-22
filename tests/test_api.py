"""Phase 5 — pipeline orchestration and API tests."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.data.loader import RestaurantStore
from app.data.models import HardConstraints, QueryIntent
from app.main import app
from app.pipeline.orchestrator import Orchestrator

FIXTURE = "tests/fixtures/sample_restaurants.json"


# ---------------------------------------------------------------------------
# Mock LLM clients
# ---------------------------------------------------------------------------


class MockIntentLLM:
    """Returns a fixed intent payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def complete_json(self, *args: Any, **kwargs: Any) -> dict:
        return self.payload


class SmartRankingLLM:
    """Parses candidate IDs from the prompt and ranks the first top_n."""

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema: dict, **kwargs: Any
    ) -> dict:
        ids = re.findall(r'"restaurant_id":\s*"([^"]+)"', user_prompt)
        rankings = [
            {
                "restaurant_id": rid,
                "match_score": round(0.95 - i * 0.1, 2),
                "reason": "Matches the requested cuisine and budget.",
            }
            for i, rid in enumerate(ids[:5])
        ]
        return {"rankings": rankings}


def _install_orchestrator(
    client: TestClient,
    *,
    intent_payload: dict[str, Any] | None = None,
    ranking_llm: Any | None = None,
    store_path: str = FIXTURE,
) -> None:
    """Replace the app orchestrator with one backed by mocks + fixture data."""
    store = RestaurantStore.from_file(store_path)
    intent_llm = MockIntentLLM(intent_payload) if intent_payload is not None else None
    client.app.state.restaurant_store = store
    client.app.state.orchestrator = Orchestrator(
        store,
        intent_llm=intent_llm,
        ranking_llm=ranking_llm,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_recommend_happy_path_with_mocked_groq() -> None:
    with TestClient(app) as client:
        _install_orchestrator(
            client,
            intent_payload={
                "hard_constraints": {"city": "bengaluru", "locality": "indiranagar"},
                "soft_preferences": ["cozy", "romantic"],
            },
            ranking_llm=SmartRankingLLM(),
        )
        resp = client.post(
            "/recommend",
            json={
                "query": "cozy romantic vegetarian place in Indiranagar",
                "top_n": 3,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "query_understood" in body
    assert "hard_constraints" in body["query_understood"]
    assert body["query_understood"]["soft_preferences"] == ["cozy", "romantic"]

    recs = body["recommendations"]
    assert 1 <= len(recs) <= 3
    valid_ids = {"R001", "R002", "R003"}
    for rec in recs:
        assert rec["restaurant_id"] in valid_ids
        assert "match_score" in rec
        assert "rank" in rec
        assert rec["reason"]

    assert body["meta"]["ranker"] == "groq"
    assert body["meta"]["latency_ms"] >= 0
    assert body["meta"]["groq_model"] is not None


def test_recommend_filters_only_skips_llm() -> None:
    with TestClient(app) as client:
        _install_orchestrator(client, ranking_llm=SmartRankingLLM())
        resp = client.post(
            "/recommend",
            json={"filters": {"city": "Bengaluru", "is_veg": True}, "top_n": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["query_understood"]["hard_constraints"]["city"] == "bengaluru"
    assert all(
        r["is_veg"] in ("Veg", "Both") for r in body["recommendations"]
    )


# ---------------------------------------------------------------------------
# Validation errors (400)
# ---------------------------------------------------------------------------


def test_recommend_empty_body_returns_400() -> None:
    with TestClient(app) as client:
        resp = client.post("/recommend", json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_recommend_top_n_too_large_returns_400() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/recommend", json={"query": "veg food", "top_n": 21}
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_recommend_invalid_filter_type_returns_400() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/recommend",
            json={"query": "veg food", "filters": {"min_rating": "four"}},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Empty results (200 + notes)
# ---------------------------------------------------------------------------


def test_recommend_empty_results_returns_200_with_notes() -> None:
    with TestClient(app) as client:
        _install_orchestrator(client, ranking_llm=SmartRankingLLM())
        resp = client.post(
            "/recommend",
            json={"filters": {"city": "atlantis"}, "top_n": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendations"] == []
    assert body["notes"]
    assert body["meta"]["ranker"] == "none"


# ---------------------------------------------------------------------------
# Health + restaurant detail
# ---------------------------------------------------------------------------


def test_health_full_contract() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dataset_loaded"] is True
    assert body["restaurant_count"] > 0
    assert "groq_configured" in body
    assert "groq_model_intent" in body
    assert "groq_model_rank" in body


def test_get_restaurant_by_id_and_404() -> None:
    with TestClient(app) as client:
        _install_orchestrator(client, ranking_llm=SmartRankingLLM())
        ok = client.get("/restaurants/R001")
        missing = client.get("/restaurants/NOPE")

    assert ok.status_code == 200
    assert ok.json()["restaurant_id"] == "R001"
    assert missing.status_code == 404


def test_openapi_docs_available() -> None:
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/recommend" in paths
    assert "/health" in paths
