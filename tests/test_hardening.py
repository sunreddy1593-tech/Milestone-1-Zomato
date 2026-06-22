"""Phase 6 — edge cases, hardening and observability tests."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import InternalServerError, RateLimitError

from app.data.loader import RestaurantStore
from app.intent.parser import IntentParser
from app.llm.groq_client import GroqClient, GroqClientError
from app.main import app
from app.pipeline.orchestrator import Orchestrator
from app.ranking.ranker import Ranker

FIXTURE = "tests/fixtures/sample_restaurants.json"


# ---------------------------------------------------------------------------
# Helpers to build Groq SDK exceptions
# ---------------------------------------------------------------------------


def _rate_limit_error() -> RateLimitError:
    req = httpx.Request("POST", "https://api.groq.com/v1/chat")
    resp = httpx.Response(429, request=req)
    return RateLimitError("rate limited", response=resp, body=None)


def _server_error() -> InternalServerError:
    req = httpx.Request("POST", "https://api.groq.com/v1/chat")
    resp = httpx.Response(503, request=req)
    return InternalServerError("server error", response=resp, body=None)


def _ok_response(content: str) -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


# ---------------------------------------------------------------------------
# Groq client resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_backoff_recovers_after_429() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(
        side_effect=[_rate_limit_error(), _ok_response('{"ok": true}')]
    )
    client = GroqClient(
        api_key="x", client=mock_groq, timeout_seconds=5, backoff_base_seconds=0
    )
    result = await client.complete_json("s", "u", {})
    assert result == {"ok": True}
    assert mock_groq.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_groq_429_exhausted_raises() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(side_effect=_rate_limit_error())
    client = GroqClient(
        api_key="x",
        client=mock_groq,
        timeout_seconds=5,
        backoff_base_seconds=0,
        max_rate_limit_retries=2,
    )
    with pytest.raises(GroqClientError, match="rate limit"):
        await client.complete_json("s", "u", {})
    assert mock_groq.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_groq_5xx_then_success() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(
        side_effect=[_server_error(), _ok_response('{"ok": 1}')]
    )
    client = GroqClient(
        api_key="x", client=mock_groq, timeout_seconds=5, backoff_base_seconds=0
    )
    result = await client.complete_json("s", "u", {})
    assert result == {"ok": 1}
    assert mock_groq.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_groq_timeout_raises_client_error() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
    client = GroqClient(
        api_key="x", client=mock_groq, timeout_seconds=1, backoff_base_seconds=0
    )
    with pytest.raises(GroqClientError, match="timed out"):
        await client.complete_json("s", "u", {})


# ---------------------------------------------------------------------------
# Mock LLM clients for pipeline-level tests
# ---------------------------------------------------------------------------


class MockIntentLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def complete_json(self, *args: Any, **kwargs: Any) -> dict:
        return self.payload


class SmartRankingLLM:
    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema: dict, **kwargs: Any
    ) -> dict:
        ids = re.findall(r'"restaurant_id":\s*"([^"]+)"', user_prompt)
        return {
            "rankings": [
                {"restaurant_id": rid, "match_score": 0.8, "reason": "Good fit."}
                for rid in ids[:5]
            ]
        }


# ---------------------------------------------------------------------------
# Vague query + no-location handling
# ---------------------------------------------------------------------------


def test_vague_query_defaults_to_high_rated_with_note() -> None:
    with TestClient(app) as client:
        store = RestaurantStore.from_file(FIXTURE)
        parser = IntentParser(
            llm_client=MockIntentLLM({"hard_constraints": {}, "soft_preferences": []}),
            default_city="Bengaluru",
        )
        client.app.state.restaurant_store = store
        client.app.state.orchestrator = Orchestrator(
            store,
            intent_parser=parser,
            ranker=Ranker(llm_client=SmartRankingLLM()),
        )
        resp = client.post("/recommend", json={"query": "somewhere nice to eat"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] and "broad" in body["notes"].lower()
    assert body["query_understood"]["hard_constraints"]["min_rating"] == 4.0


def test_no_location_and_no_default_city_returns_422() -> None:
    with TestClient(app) as client:
        store = RestaurantStore.from_file(FIXTURE)
        parser = IntentParser(
            llm_client=MockIntentLLM({"hard_constraints": {}, "soft_preferences": []}),
            default_city="",
        )
        client.app.state.restaurant_store = store
        client.app.state.orchestrator = Orchestrator(
            store,
            intent_parser=parser,
            ranker=Ranker(llm_client=SmartRankingLLM()),
        )
        resp = client.post("/recommend", json={"query": "good food please"})

    assert resp.status_code == 422
    assert resp.json()["error"] == "ambiguous_query"


# ---------------------------------------------------------------------------
# Empty dataset → 503 + degraded health
# ---------------------------------------------------------------------------


def test_empty_dataset_recommend_returns_503() -> None:
    with TestClient(app) as client:
        empty_store = RestaurantStore([])
        client.app.state.restaurant_store = empty_store
        client.app.state.orchestrator = Orchestrator(empty_store)
        resp = client.post(
            "/recommend", json={"filters": {"city": "Bengaluru"}}
        )

    assert resp.status_code == 503
    assert resp.json()["error"] == "service_unavailable"


def test_empty_dataset_health_degraded() -> None:
    with TestClient(app) as client:
        client.app.state.restaurant_store = RestaurantStore([])
        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dataset_loaded"] is False
    assert body["restaurant_count"] == 0


# ---------------------------------------------------------------------------
# Error envelope consistency
# ---------------------------------------------------------------------------


def test_404_restaurant_error_envelope() -> None:
    with TestClient(app) as client:
        resp = client.get("/restaurants/DOES_NOT_EXIST")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"
