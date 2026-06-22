"""Phase 3 — Groq client and intent parser tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.models import HardConstraints, QueryIntent
from app.intent.fallback import rule_based_parse
from app.intent.parser import (
    IntentParser,
    apply_default_city,
    intent_from_llm_payload,
    merge_explicit_filters,
)
from app.llm.groq_client import GroqClient, GroqClientError


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """In-memory LLM stub for parser tests."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_retries: int = 1,
    ) -> dict:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise GroqClientError("No mock responses configured")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_client_parses_json_response() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"hard_constraints": {}, "soft_preferences": ["cozy"]}'))]
        )
    )
    client = GroqClient(api_key="test-key", client=mock_groq, timeout_seconds=5)

    result = await client.complete_json("system", "user", {}, model="test-model")

    assert result["soft_preferences"] == ["cozy"]
    mock_groq.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_groq.chat.completions.create.await_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["model"] == "test-model"


@pytest.mark.asyncio
async def test_groq_client_retries_on_invalid_json() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(
        side_effect=[
            MagicMock(choices=[MagicMock(message=MagicMock(content="not json"))]),
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"hard_constraints": {"city": "bengaluru"}, "soft_preferences": []}'
                        )
                    )
                ]
            ),
        ]
    )
    client = GroqClient(api_key="test-key", client=mock_groq, timeout_seconds=5)

    result = await client.complete_json("system", "user", {}, max_retries=1)

    assert result["hard_constraints"]["city"] == "bengaluru"
    assert mock_groq.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_groq_client_raises_after_exhausted_json_retries() -> None:
    mock_groq = MagicMock()
    mock_groq.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="still not json"))])
    )
    client = GroqClient(api_key="test-key", client=mock_groq, timeout_seconds=5)

    with pytest.raises(GroqClientError, match="invalid JSON"):
        await client.complete_json("system", "user", {}, max_retries=1)


# ---------------------------------------------------------------------------
# Merge / payload helpers
# ---------------------------------------------------------------------------


def test_explicit_filters_override_llm_parsed_values() -> None:
    intent = QueryIntent(
        original_query="Indiranagar veg place",
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            is_veg=True,
        ),
        soft_preferences=["cozy"],
    )
    merged = merge_explicit_filters(
        intent,
        {"city": "Mumbai", "min_rating": 4.5},
    )
    assert merged.hard_constraints.city == "mumbai"
    assert merged.hard_constraints.locality == "indiranagar"
    assert merged.hard_constraints.min_rating == 4.5


def test_apply_default_city_when_no_location() -> None:
    intent = QueryIntent(
        original_query="cozy vegetarian place for a date",
        hard_constraints=HardConstraints(is_veg=True),
    )
    updated = apply_default_city(intent, "Bengaluru")
    assert updated.hard_constraints.city == "bengaluru"
    assert updated.hard_constraints.locality is None


def test_intent_from_llm_payload_normalises_locations() -> None:
    intent = intent_from_llm_payload(
        {
            "hard_constraints": {
                "city": "Bengaluru",
                "locality": "Indiranagar",
                "is_veg": True,
            },
            "soft_preferences": ["romantic", "cozy"],
        },
        original_query="test",
    )
    assert intent.hard_constraints.city == "bengaluru"
    assert intent.hard_constraints.locality == "indiranagar"
    assert intent.soft_preferences == ["romantic", "cozy"]


# ---------------------------------------------------------------------------
# IntentParser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parser_uses_groq_response() -> None:
    mock = MockLLMClient(
        responses=[
            {
                "hard_constraints": {
                    "city": "bengaluru",
                    "locality": "indiranagar",
                    "is_veg": True,
                    "max_cost_for_two": 1500,
                },
                "soft_preferences": ["cozy", "romantic", "date-night"],
            }
        ]
    )
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        "cozy budget-friendly vegetarian place for a date in Indiranagar"
    )

    assert intent.hard_constraints.locality == "indiranagar"
    assert intent.hard_constraints.is_veg is True
    assert "cozy" in intent.soft_preferences
    assert len(mock.calls) == 1


@pytest.mark.asyncio
async def test_parser_explicit_filters_override_groq() -> None:
    mock = MockLLMClient(
        responses=[
            {
                "hard_constraints": {
                    "city": "bengaluru",
                    "locality": "indiranagar",
                },
                "soft_preferences": [],
            }
        ]
    )
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        "restaurants in Indiranagar",
        filters={"city": "Mumbai", "is_veg": True},
    )

    assert intent.hard_constraints.city == "mumbai"
    assert intent.hard_constraints.is_veg is True


@pytest.mark.asyncio
async def test_parser_falls_back_on_groq_error() -> None:
    mock = MockLLMClient(error=GroqClientError("API down"))
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        "Cheap vegetarian street food near MG Road, open right now."
    )

    assert intent.hard_constraints.is_veg is True
    assert intent.hard_constraints.open_now is True
    assert "mg road" in (intent.hard_constraints.locality or "")
    assert "cheap" in intent.soft_preferences or intent.hard_constraints.max_cost_for_two


@pytest.mark.asyncio
async def test_parser_filters_only_skips_llm() -> None:
    mock = MockLLMClient(
        responses=[{"hard_constraints": {}, "soft_preferences": ["should-not-be-used"]}]
    )
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        None,
        filters={"city": "Bengaluru", "is_veg": True, "min_rating": 4.0},
    )

    assert intent.hard_constraints.city == "bengaluru"
    assert intent.hard_constraints.is_veg is True
    assert intent.hard_constraints.min_rating == 4.0
    assert intent.soft_preferences == []
    assert mock.calls == []


@pytest.mark.asyncio
async def test_golden_query_cheap_veg_mg_road_with_mock_groq() -> None:
    mock = MockLLMClient(
        responses=[
            {
                "hard_constraints": {
                    "locality": "mg road",
                    "is_veg": True,
                    "open_now": True,
                    "max_cost_for_two": 800,
                    "max_price_range": 1,
                },
                "soft_preferences": ["street food", "cheap"],
            }
        ]
    )
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        "Cheap vegetarian street food near MG Road, open right now."
    )

    hc = intent.hard_constraints
    assert hc.is_veg is True
    assert hc.open_now is True
    assert hc.locality == "mg road"
    assert hc.max_cost_for_two == 800 or hc.max_price_range == 1
    assert any(p in intent.soft_preferences for p in ("cheap", "street food"))


@pytest.mark.asyncio
async def test_golden_query_romantic_rooftop_with_mock_groq() -> None:
    mock = MockLLMClient(
        responses=[
            {
                "hard_constraints": {},
                "soft_preferences": ["romantic", "rooftop", "anniversary"],
            }
        ]
    )
    parser = IntentParser(llm_client=mock, default_city="Bengaluru")

    intent = await parser.parse(
        "Romantic rooftop restaurant for an anniversary dinner, budget no concern."
    )

    assert intent.hard_constraints.max_cost_for_two is None
    assert "romantic" in intent.soft_preferences
    assert "rooftop" in intent.soft_preferences


# ---------------------------------------------------------------------------
# Rule-based fallback (direct)
# ---------------------------------------------------------------------------


def test_rule_based_fallback_cheap_veg_open_now() -> None:
    intent = rule_based_parse(
        "Cheap vegetarian street food near MG Road, open right now.",
        default_city="Bengaluru",
    )
    assert intent.hard_constraints.is_veg is True
    assert intent.hard_constraints.open_now is True
    assert intent.hard_constraints.locality == "mg road"


def test_rule_based_no_budget_leaves_max_cost_unset() -> None:
    intent = rule_based_parse(
        "Romantic rooftop restaurant for an anniversary dinner, budget no concern.",
        default_city="Bengaluru",
    )
    assert intent.hard_constraints.max_cost_for_two is None
    assert "romantic" in intent.soft_preferences


def test_rule_based_nonveg_keyword() -> None:
    intent = rule_based_parse("non-vegetarian BBQ place", default_city="Bengaluru")
    assert intent.hard_constraints.is_veg is False


@pytest.mark.asyncio
async def test_parser_without_llm_client_uses_rules() -> None:
    with patch("app.intent.parser.build_groq_client", return_value=None):
        parser = IntentParser(default_city="Bengaluru")
        intent = await parser.parse(
            "Best-rated Chinese delivery under Rs.800 for two."
        )

    assert intent.hard_constraints.has_online_delivery is True
    assert intent.hard_constraints.max_cost_for_two == 800
    assert any("chinese" in c.lower() for c in intent.hard_constraints.cuisines)
