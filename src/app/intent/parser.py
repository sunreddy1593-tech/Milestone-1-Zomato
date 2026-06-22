"""Intent parser — NL query + explicit filters → structured QueryIntent."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.config import settings
from app.data.models import HardConstraints, QueryIntent
from app.intent.fallback import rule_based_parse
from app.intent.prompts import (
    INTENT_JSON_SCHEMA,
    build_intent_system_prompt,
    build_intent_user_prompt,
)
from app.llm.client import LLMClient
from app.llm.groq_client import GroqClient, GroqClientError, build_groq_client

logger = logging.getLogger(__name__)

_FILTER_FIELD_NAMES = frozenset(HardConstraints.model_fields.keys())


def _normalise_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _coerce_hard_constraints(raw: dict[str, Any]) -> HardConstraints:
    """Build ``HardConstraints`` from a loose dict, normalising location fields."""
    data = dict(raw or {})
    if "city" in data:
        data["city"] = _normalise_str(data["city"])
    if "locality" in data:
        data["locality"] = _normalise_str(data["locality"])
    if "cuisines" in data and data["cuisines"] is None:
        data["cuisines"] = []
    return HardConstraints.model_validate(data)


def intent_from_llm_payload(
    payload: dict[str, Any],
    *,
    original_query: str,
) -> QueryIntent:
    """Convert an LLM JSON payload into a validated ``QueryIntent``."""
    hard_raw = payload.get("hard_constraints") or {}
    soft = payload.get("soft_preferences") or []
    if not isinstance(soft, list):
        soft = []
    soft = [str(item).strip() for item in soft if str(item).strip()]

    return QueryIntent(
        hard_constraints=_coerce_hard_constraints(hard_raw),
        soft_preferences=soft,
        original_query=original_query,
    )


def merge_explicit_filters(
    intent: QueryIntent,
    filters: dict[str, Any] | None,
) -> QueryIntent:
    """Apply explicit API filters over parsed intent (override policy)."""
    if not filters:
        return intent

    merged = intent.model_copy(deep=True)
    constraint_data = merged.hard_constraints.model_dump()

    for key, value in filters.items():
        if key not in _FILTER_FIELD_NAMES:
            continue
        if value is None:
            continue
        if key in ("city", "locality") and isinstance(value, str):
            constraint_data[key] = value.strip().lower()
        else:
            constraint_data[key] = value

    merged.hard_constraints = HardConstraints.model_validate(constraint_data)
    return merged


def apply_default_city(intent: QueryIntent, default_city: str | None) -> QueryIntent:
    """Fill ``city`` from config when no location was parsed."""
    if not default_city:
        return intent
    hc = intent.hard_constraints
    if hc.city or hc.locality:
        return intent

    updated = intent.model_copy(deep=True)
    updated.hard_constraints.city = default_city.strip().lower()
    return updated


def intent_from_filters_only(
    filters: dict[str, Any],
    *,
    original_query: str = "",
) -> QueryIntent:
    """Build intent directly from explicit filters (no NL parsing)."""
    constraint_data = {
        key: filters[key]
        for key in _FILTER_FIELD_NAMES
        if key in filters and filters[key] is not None
    }
    if "city" in constraint_data and isinstance(constraint_data["city"], str):
        constraint_data["city"] = constraint_data["city"].strip().lower()
    if "locality" in constraint_data and isinstance(constraint_data["locality"], str):
        constraint_data["locality"] = constraint_data["locality"].strip().lower()

    return QueryIntent(
        hard_constraints=HardConstraints.model_validate(constraint_data),
        soft_preferences=[],
        original_query=original_query,
    )


class IntentParser:
    """Parse natural-language queries into ``QueryIntent`` using Groq + fallback rules."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        default_city: str | None = None,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client if llm_client is not None else build_groq_client(model=model)
        self._model = model or settings.groq_model_intent
        self._default_city = default_city if default_city is not None else settings.default_city

    async def parse(
        self,
        query: str | None,
        filters: dict[str, Any] | None = None,
    ) -> QueryIntent:
        """Parse ``query`` and merge explicit ``filters`` into a ``QueryIntent``."""
        filters = filters or {}
        text = (query or "").strip()

        if not text and filters:
            intent = intent_from_filters_only(filters)
            return apply_default_city(intent, self._default_city)

        if not text and not filters:
            return QueryIntent(original_query="")

        intent = await self._parse_natural_language(text)
        intent = merge_explicit_filters(intent, filters)
        return apply_default_city(intent, self._default_city)

    async def _parse_natural_language(self, query: str) -> QueryIntent:
        if self._llm is not None:
            try:
                payload = await self._llm.complete_json(
                    build_intent_system_prompt(),
                    build_intent_user_prompt(query, {}),
                    INTENT_JSON_SCHEMA,
                    model=self._model,
                    temperature=0.2,
                    max_retries=1,
                )
                return intent_from_llm_payload(payload, original_query=query)
            except (GroqClientError, ValidationError, TypeError, ValueError) as exc:
                logger.warning("Groq intent parsing failed, using rule fallback: %s", exc)

        return rule_based_parse(query, default_city=self._default_city)


# Module-level default parser for convenience in later phases.
default_intent_parser = IntentParser()
