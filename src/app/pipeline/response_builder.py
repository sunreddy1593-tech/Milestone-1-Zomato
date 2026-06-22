"""Assemble the final `/recommend` response from pipeline outputs."""

from __future__ import annotations

from app.api.schemas import (
    QueryUnderstood,
    RecommendResponse,
    ResponseMeta,
)
from app.config import settings
from app.data.models import QueryIntent
from app.ranking.ranker import RankingResult
from app.retrieval.retriever import RetrievalResult


def _build_notes(
    retrieval: RetrievalResult,
    *,
    empty: bool = False,
    extra_notes: list[str] | None = None,
) -> str | None:
    """Compose user-facing notes from extra context, relaxations, empty results."""
    notes: list[str] = []
    if extra_notes:
        notes.extend(extra_notes)
    if retrieval.relaxed_constraints:
        notes.extend(retrieval.relaxed_constraints)
    if empty:
        notes.append(
            "No restaurants matched your constraints, even after relaxing them. "
            "Try broadening the location, cuisine, or budget."
        )
    return " ".join(notes) if notes else None


def _query_understood(intent: QueryIntent) -> QueryUnderstood:
    return QueryUnderstood(
        hard_constraints=intent.hard_constraints.model_dump(exclude_none=True),
        soft_preferences=intent.soft_preferences,
    )


def build_response(
    intent: QueryIntent,
    retrieval: RetrievalResult,
    ranking: RankingResult,
    *,
    latency_ms: int,
    extra_notes: list[str] | None = None,
) -> RecommendResponse:
    """Build a populated recommendation response."""
    groq_model = settings.groq_model_rank if ranking.ranker == "groq" else None
    return RecommendResponse(
        query_understood=_query_understood(intent),
        recommendations=ranking.recommendations,
        notes=_build_notes(retrieval, extra_notes=extra_notes),
        meta=ResponseMeta(
            candidate_count=retrieval.total_before_limit,
            latency_ms=latency_ms,
            ranker=ranking.ranker,
            groq_model=groq_model,
        ),
    )


def build_empty_response(
    intent: QueryIntent,
    retrieval: RetrievalResult,
    *,
    latency_ms: int,
    extra_notes: list[str] | None = None,
) -> RecommendResponse:
    """Build a 200 response with no recommendations and actionable notes."""
    return RecommendResponse(
        query_understood=_query_understood(intent),
        recommendations=[],
        notes=_build_notes(retrieval, empty=True, extra_notes=extra_notes),
        meta=ResponseMeta(
            candidate_count=retrieval.total_before_limit,
            latency_ms=latency_ms,
            ranker="none",
            groq_model=None,
        ),
    )
