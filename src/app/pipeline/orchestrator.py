"""Pipeline orchestrator — wires intent → retrieval → ranking → response.

Phase 9 stretch features layered in additively (all optional / off by default
where they would change behaviour):
  - 9.2 distance-based ranking (graceful when coordinates are absent)
  - 9.3 multi-turn conversational refinement (``recommend_chat``)
  - 9.4 dependency-free semantic pre-rank of the candidate shortlist
  - 9.5 TTL + LRU response caching
  - 9.6 lightweight personalization profiles
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from app.api.errors import AmbiguousQueryError
from app.api.schemas import ChatRequest, RecommendRequest, RecommendResponse
from app.config import settings
from app.data.loader import RestaurantStore
from app.data.models import HardConstraints, QueryIntent
from app.intent.parser import IntentParser
from app.llm.client import LLMClient
from app.pipeline.cache import ResponseCache, make_cache_key
from app.pipeline.profiles import ProfileStore
from app.pipeline.response_builder import build_empty_response, build_response
from app.pipeline.sessions import SessionState, SessionStore
from app.ranking.ranker import Ranker
from app.retrieval.retriever import Retriever
from app.retrieval.semantic import SemanticIndex
from app.utils.geo import distance_for

logger = logging.getLogger(__name__)

_VAGUE_DEFAULT_MIN_RATING = 4.0

# Simple refinement keyword → action map for conversational turns (9.3).
_CHEAPER_WORDS = ("cheaper", "less expensive", "budget", "affordable", "lower price")
_AMBIANCE_REFINEMENTS = (
    "outdoor seating",
    "rooftop",
    "quiet",
    "cozy",
    "romantic",
    "family friendly",
    "live music",
    "pet friendly",
)


def _query_hash(query: str | None) -> str:
    """Stable short hash for logging without leaking full query text/PII."""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:8]


def _is_vague(intent: QueryIntent) -> bool:
    """A broad query: free text present but no specific constraints or preferences."""
    if not intent.original_query.strip():
        return False
    if intent.soft_preferences:
        return False
    hc = intent.hard_constraints
    specific = any(
        [
            hc.locality,
            hc.cuisines,
            hc.is_veg is not None,
            hc.max_cost_for_two is not None,
            hc.min_rating is not None,
            hc.max_price_range is not None,
            hc.open_now is not None,
            hc.has_table_booking is not None,
            hc.has_online_delivery is not None,
        ]
    )
    return not specific


class Orchestrator:
    """End-to-end recommendation flow coordinator."""

    def __init__(
        self,
        store: RestaurantStore,
        *,
        intent_parser: IntentParser | None = None,
        retriever: Retriever | None = None,
        ranker: Ranker | None = None,
        intent_llm: LLMClient | None = None,
        ranking_llm: LLMClient | None = None,
        max_candidates: int | None = None,
        cache: ResponseCache | None = None,
        sessions: SessionStore | None = None,
        profiles: ProfileStore | None = None,
        semantic_index: SemanticIndex | None = None,
    ) -> None:
        self._store = store
        self._max_candidates = max_candidates or settings.max_candidates
        self._retriever = retriever or Retriever(store, timezone=settings.timezone)
        self._intent_parser = intent_parser or IntentParser(llm_client=intent_llm)
        self._ranker = ranker or Ranker(llm_client=ranking_llm)

        self._cache = cache if cache is not None else (
            ResponseCache(
                ttl_seconds=settings.cache_ttl_seconds,
                max_entries=settings.cache_max_entries,
            )
            if settings.cache_enabled
            else None
        )
        self.sessions = sessions or SessionStore(
            ttl_seconds=settings.session_ttl_seconds,
            max_entries=settings.session_max_entries,
        )
        self.profiles = profiles or ProfileStore()
        # Semantic index is built lazily on first use to avoid startup cost for
        # filter-only workloads; an instance may also be injected/shared.
        self._semantic_index = semantic_index

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    async def recommend(self, request: RecommendRequest) -> RecommendResponse:
        """Run the full pipeline (with caching) and return a populated response."""
        start = time.perf_counter()
        qhash = _query_hash(request.query)

        cache_key = self._cache_key(request)
        if self._cache is not None and cache_key is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                latency_ms = int((time.perf_counter() - start) * 1000)
                clone = cached.model_copy(deep=True)
                clone.meta.cached = True
                clone.meta.latency_ms = latency_ms
                logger.info("recommend qhash=%s cache=hit latency_ms=%d", qhash, latency_ms)
                return clone

        filters = (
            request.filters.model_dump(exclude_none=True) if request.filters else {}
        )
        intent = await self._intent_parser.parse(request.query, filters)
        self._guard_location(intent)

        extra_notes: list[str] = []
        if _is_vague(intent):
            self._apply_vague_default(intent, extra_notes)

        personalized = self._apply_personalization(intent, request.user_id)

        response = await self._run_pipeline(
            intent,
            top_n=request.top_n,
            user_lat=request.user_lat,
            user_lng=request.user_lng,
            max_distance_km=request.max_distance_km,
            extra_notes=extra_notes,
            start=start,
            qhash=qhash,
        )
        response.meta.personalized = personalized

        if request.user_id:
            self._observe_profile(request.user_id, response)

        if self._cache is not None and cache_key is not None and response.recommendations:
            self._cache.set(cache_key, response)

        return response

    async def recommend_chat(self, request: ChatRequest) -> RecommendResponse:
        """Conversational turn: carry prior context and exclude shown results."""
        start = time.perf_counter()
        qhash = _query_hash(request.query)

        session_id, state = self.sessions.get_or_create(request.session_id)

        filters = (
            request.filters.model_dump(exclude_none=True) if request.filters else {}
        )
        intent = await self._intent_parser.parse(request.query, filters)
        intent = self._merge_session(intent, state)

        extra_notes: list[str] = []
        self._apply_refinements(request.query, intent, extra_notes)
        self._guard_location(intent)
        if _is_vague(intent):
            self._apply_vague_default(intent, extra_notes)

        personalized = self._apply_personalization(intent, request.user_id)

        exclude_ids = set(state.shown_ids)
        response = await self._run_pipeline(
            intent,
            top_n=request.top_n,
            user_lat=request.user_lat,
            user_lng=request.user_lng,
            max_distance_km=None,
            exclude_ids=exclude_ids,
            extra_notes=extra_notes,
            start=start,
            qhash=qhash,
        )
        response.meta.personalized = personalized
        response.session_id = session_id

        # Persist accumulated context for the next turn.
        state.hard_constraints = intent.hard_constraints.model_dump(exclude_none=True)
        state.soft_preferences = list(intent.soft_preferences)
        new_ids = [r.restaurant_id for r in response.recommendations]
        state.shown_ids = list(dict.fromkeys([*state.shown_ids, *new_ids]))
        state.turns += 1
        self.sessions.save(session_id, state)

        if request.user_id:
            self._observe_profile(request.user_id, response)

        return response

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        intent: QueryIntent,
        *,
        top_n: int,
        user_lat: float | None,
        user_lng: float | None,
        max_distance_km: float | None,
        start: float,
        qhash: str,
        exclude_ids: set[str] | None = None,
        extra_notes: list[str] | None = None,
    ) -> RecommendResponse:
        extra_notes = extra_notes or []
        retrieval = self._retriever.retrieve_candidates(
            intent, max_candidates=self._max_candidates
        )

        if not retrieval.candidates:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "recommend qhash=%s candidates=0 relaxations=%d ranker=none latency_ms=%d",
                qhash,
                len(retrieval.relaxed_constraints),
                latency_ms,
            )
            return build_empty_response(
                intent, retrieval, latency_ms=latency_ms, extra_notes=extra_notes
            )

        candidates = list(retrieval.candidates)

        # 9.3 — drop already-shown restaurants, unless that empties the list.
        if exclude_ids:
            filtered = [c for c in candidates if c.restaurant_id not in exclude_ids]
            if filtered:
                candidates = filtered
            else:
                extra_notes.append(
                    "No new matches beyond what you've already seen; showing the best again."
                )

        # 9.4 — semantic pre-rank of the candidate shortlist.
        used_semantic = False
        semantic = self._get_semantic_index()
        if semantic is not None and intent.original_query.strip():
            candidates = self._semantic_reorder(candidates, intent.original_query, semantic)
            used_semantic = True

        ranking = await self._ranker.rank(
            candidates, intent, top_n=top_n, preranked=used_semantic
        )

        # 9.2 — attach distance (None when coordinates are unavailable) and
        # optionally drop results beyond the requested radius.
        self._attach_distance(ranking, user_lat, user_lng)
        if max_distance_km is not None:
            kept = [
                r
                for r in ranking.recommendations
                if r.distance_km is None or r.distance_km <= max_distance_km
            ]
            ranking.recommendations = kept
            for idx, rec in enumerate(ranking.recommendations, start=1):
                rec.rank = idx

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "recommend qhash=%s candidates=%d relaxations=%d ranker=%s semantic=%s latency_ms=%d",
            qhash,
            retrieval.total_before_limit,
            len(retrieval.relaxed_constraints),
            ranking.ranker,
            used_semantic,
            latency_ms,
        )

        if not ranking.recommendations:
            return build_empty_response(
                intent, retrieval, latency_ms=latency_ms, extra_notes=extra_notes
            )

        response = build_response(
            intent, retrieval, ranking, latency_ms=latency_ms, extra_notes=extra_notes
        )
        response.meta.used_semantic = used_semantic
        return response

    # ------------------------------------------------------------------
    # Feature helpers
    # ------------------------------------------------------------------

    def _get_semantic_index(self) -> SemanticIndex | None:
        if not settings.semantic_enabled:
            return None
        if self._semantic_index is None:
            self._semantic_index = SemanticIndex(self._store.get_all())
            logger.info("Built semantic index over %d restaurants", len(self._semantic_index))
        return self._semantic_index

    @staticmethod
    def _semantic_reorder(candidates, query: str, semantic: SemanticIndex):
        ids = [c.restaurant_id for c in candidates]
        sims = semantic.score(query, ids)
        w = settings.semantic_weight

        def blended(c) -> float:
            rating_norm = max(0.0, min(c.rating, 5.0)) / 5.0
            return (1 - w) * rating_norm + w * sims.get(c.restaurant_id, 0.0)

        return sorted(
            candidates,
            key=lambda c: (-blended(c), -c.votes, c.restaurant_id),
        )

    def _attach_distance(
        self, ranking, user_lat: float | None, user_lng: float | None
    ) -> None:
        if user_lat is None or user_lng is None:
            return
        for rec in ranking.recommendations:
            r = self._store.get_by_id(rec.restaurant_id)
            if r is not None:
                rec.distance_km = distance_for(
                    r.latitude, r.longitude, user_lat, user_lng
                )

    def _apply_personalization(self, intent: QueryIntent, user_id: str | None) -> bool:
        if not (settings.personalization_enabled and user_id):
            return False
        learned = self.profiles.preferred(user_id)
        if not learned:
            return False
        existing = {p.lower() for p in intent.soft_preferences}
        added = [p for p in learned if p.lower() not in existing]
        if not added:
            return False
        intent.soft_preferences = [*intent.soft_preferences, *added]
        return True

    def _observe_profile(self, user_id: str, response: RecommendResponse) -> None:
        cuisines: list[str] = []
        ambiance: list[str] = []
        for rec in response.recommendations:
            cuisines.extend(rec.cuisines)
            ambiance.extend(rec.ambiance_tags)
        self.profiles.observe(user_id, cuisines=cuisines, ambiance_tags=ambiance)

    @staticmethod
    def _apply_vague_default(intent: QueryIntent, extra_notes: list[str]) -> None:
        hc = intent.hard_constraints
        if hc.min_rating is None:
            hc.min_rating = _VAGUE_DEFAULT_MIN_RATING
        city = (hc.city or settings.default_city).title()
        extra_notes.append(
            f"Your request was broad, so showing popular highly-rated restaurants in {city}."
        )

    @staticmethod
    def _merge_session(intent: QueryIntent, state: SessionState) -> QueryIntent:
        """Fill unset constraints from prior turns and carry soft preferences."""
        if not state.hard_constraints and not state.soft_preferences:
            return intent
        data = intent.hard_constraints.model_dump()
        for key, value in state.hard_constraints.items():
            if key not in data:
                continue
            current = data.get(key)
            if current is None or (isinstance(current, list) and not current):
                data[key] = value
        intent.hard_constraints = HardConstraints.model_validate(data)

        merged_soft = list(intent.soft_preferences)
        seen = {p.lower() for p in merged_soft}
        for p in state.soft_preferences:
            if p.lower() not in seen:
                merged_soft.append(p)
                seen.add(p.lower())
        intent.soft_preferences = merged_soft
        return intent

    @staticmethod
    def _apply_refinements(
        query: str | None, intent: QueryIntent, extra_notes: list[str]
    ) -> None:
        if not query:
            return
        q = query.lower()
        hc = intent.hard_constraints

        if any(w in q for w in _CHEAPER_WORDS):
            if hc.max_price_range is not None and hc.max_price_range > 1:
                hc.max_price_range -= 1
            elif hc.max_cost_for_two is not None:
                hc.max_cost_for_two = max(100, int(hc.max_cost_for_two * 0.7))
            else:
                hc.max_price_range = 2
            extra_notes.append("Narrowed to more budget-friendly options.")

        seen = {p.lower() for p in intent.soft_preferences}
        for phrase in _AMBIANCE_REFINEMENTS:
            if phrase in q and phrase not in seen:
                intent.soft_preferences.append(phrase)
                seen.add(phrase)

    def _cache_key(self, request: RecommendRequest) -> str | None:
        if self._cache is None:
            return None
        payload: dict[str, Any] = {
            "query": (request.query or "").strip().lower(),
            "filters": request.filters.model_dump(exclude_none=True)
            if request.filters
            else {},
            "top_n": request.top_n,
            "user_lat": request.user_lat,
            "user_lng": request.user_lng,
            "max_distance_km": request.max_distance_km,
            "user_id": request.user_id,
        }
        return make_cache_key(payload)

    def cache_stats(self) -> dict[str, int]:
        return self._cache.stats() if self._cache is not None else {}

    def clear_cache(self) -> None:
        if self._cache is not None:
            self._cache.clear()

    @staticmethod
    def _guard_location(intent: QueryIntent) -> None:
        """Require a city or locality; otherwise the query is ambiguous (422)."""
        hc = intent.hard_constraints
        if not hc.city and not hc.locality:
            raise AmbiguousQueryError(
                "Please specify a city or locality, or configure DEFAULT_CITY."
            )
