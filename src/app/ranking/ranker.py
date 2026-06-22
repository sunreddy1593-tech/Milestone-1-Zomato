"""Ranking layer — Groq-powered ranking with deterministic fallback."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.data.models import QueryIntent, Restaurant
from app.llm.client import LLMClient
from app.llm.groq_client import GroqClientError, build_groq_client
from app.ranking.fallback import _build_reason, fallback_rank
from app.ranking.prompts import (
    RANKING_JSON_SCHEMA,
    build_ranking_system_prompt,
    build_ranking_user_prompt,
)
from app.retrieval.retriever import pre_rank
from app.utils.validation import (
    backfill_rankings,
    normalise_scores_and_ranks,
    validate_ranking_ids,
)

logger = logging.getLogger(__name__)


class Recommendation(BaseModel):
    """A single ranked recommendation enriched with restaurant attributes."""

    restaurant_id: str
    name: str
    city: str
    locality: str
    cuisines: list[str]
    rating: float
    votes: int
    average_cost_for_two: int
    price_range: int
    is_veg: str
    ambiance_tags: list[str]
    has_table_booking: bool = False
    has_online_delivery: bool = False
    match_score: float | None = None
    rank: int
    reason: str
    distance_km: float | None = None


class RankingResult(BaseModel):
    """Output of the ranking layer."""

    recommendations: list[Recommendation]
    ranker: str = Field(description="'groq' or 'fallback'")


class Ranker:
    """Rank candidates with Groq, falling back to deterministic scoring."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client if llm_client is not None else build_groq_client(
            model=model or settings.groq_model_rank
        )
        self._model = model or settings.groq_model_rank

    async def rank(
        self,
        candidates: list[Restaurant],
        intent: QueryIntent,
        *,
        top_n: int = 5,
        preranked: bool = False,
    ) -> RankingResult:
        """Return top-N enriched recommendations grounded in the candidate set.

        When ``preranked`` is True the incoming ``candidates`` order is treated
        as authoritative (e.g. already reordered by semantic similarity), so the
        deterministic rating-based pre-rank is skipped for shortlisting/backfill.
        """
        if not candidates:
            return RankingResult(recommendations=[], ranker="fallback")

        by_id = {r.restaurant_id: r for r in candidates}
        ordered = list(candidates) if preranked else pre_rank(candidates)
        pre_ranked_ids = [r.restaurant_id for r in ordered]

        if self._llm is not None:
            # Only send a bounded, pre-ranked shortlist to the LLM to stay
            # within provider token limits. Validation + backfill below still
            # operate over the full candidate set.
            shortlist = ordered[: settings.llm_rank_candidates]
            try:
                rankings = await self._rank_with_llm(shortlist, intent, top_n=top_n)
                rankings = validate_ranking_ids(rankings, set(by_id.keys()))
                if rankings:
                    rankings = backfill_rankings(rankings, pre_ranked_ids, top_n=top_n)
                    recommendations = self._build_recommendations(
                        rankings, by_id, intent
                    )
                    return RankingResult(recommendations=recommendations, ranker="groq")
                logger.warning("Groq ranking produced no valid IDs; using fallback")
            except (GroqClientError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Groq ranking failed, using fallback: %s", exc)

        rankings = fallback_rank(
            candidates,
            soft_preferences=intent.soft_preferences,
            top_n=top_n,
        )
        recommendations = self._build_recommendations(rankings, by_id, intent)
        return RankingResult(recommendations=recommendations, ranker="fallback")

    async def _rank_with_llm(
        self,
        candidates: list[Restaurant],
        intent: QueryIntent,
        *,
        top_n: int,
    ) -> list[dict[str, Any]]:
        payload = await self._llm.complete_json(
            build_ranking_system_prompt(),
            build_ranking_user_prompt(
                candidates,
                query=intent.original_query,
                soft_preferences=intent.soft_preferences,
                hard_constraints=intent.hard_constraints.model_dump(exclude_none=True),
                top_n=top_n,
            ),
            RANKING_JSON_SCHEMA,
            model=self._model,
            temperature=0.2,
            max_retries=1,
        )
        rankings = payload.get("rankings", [])
        if not isinstance(rankings, list):
            raise ValueError("Groq ranking payload missing 'rankings' list")
        return rankings

    def _build_recommendations(
        self,
        rankings: list[dict[str, Any]],
        by_id: dict[str, Restaurant],
        intent: QueryIntent,
    ) -> list[Recommendation]:
        rankings = normalise_scores_and_ranks(rankings)
        recommendations: list[Recommendation] = []

        for entry in rankings:
            restaurant = by_id[entry["restaurant_id"]]
            reason = entry.get("reason")
            if not reason:
                reason = _build_reason(restaurant, intent.soft_preferences, [])
            score = entry.get("match_score")
            recommendations.append(
                Recommendation(
                    restaurant_id=restaurant.restaurant_id,
                    name=restaurant.name,
                    city=restaurant.city,
                    locality=restaurant.locality,
                    cuisines=restaurant.cuisines,
                    rating=restaurant.rating,
                    votes=restaurant.votes,
                    average_cost_for_two=restaurant.average_cost_for_two,
                    price_range=restaurant.price_range,
                    is_veg=restaurant.is_veg,
                    ambiance_tags=restaurant.ambiance_tags,
                    has_table_booking=restaurant.has_table_booking,
                    has_online_delivery=restaurant.has_online_delivery,
                    match_score=float(score) if score is not None else None,
                    rank=entry["rank"],
                    reason=reason,
                )
            )
        return recommendations
