"""API routes — /recommend, /health, /restaurants/{id}."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import ChatRequest, RecommendRequest, RecommendResponse
from app.config import settings
from app.data.loader import RestaurantStore
from app.data.models import Restaurant
from app.pipeline.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_store(request: Request) -> RestaurantStore:
    store = getattr(request.app.state, "restaurant_store", None)
    if store is None or store.count() == 0:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "message": "Dataset not loaded."},
        )
    return store


def _get_orchestrator(request: Request) -> Orchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        orchestrator = Orchestrator(_get_store(request))
        request.app.state.orchestrator = orchestrator
    return orchestrator


@router.post("/recommend", response_model=RecommendResponse, tags=["recommend"])
async def recommend(request: Request, body: RecommendRequest) -> RecommendResponse:
    """Return grounded, ranked, explainable restaurant recommendations."""
    _get_store(request)  # ensure dataset readiness (503 otherwise)
    orchestrator = _get_orchestrator(request)
    # Domain exceptions propagate to their dedicated handlers (422 / 503);
    # any other unexpected error is caught by the global 500 handler.
    return await orchestrator.recommend(body)


@router.post("/recommend/chat", response_model=RecommendResponse, tags=["recommend"])
async def recommend_chat(request: Request, body: ChatRequest) -> RecommendResponse:
    """Conversational refinement turn (Phase 9.3).

    Pass the returned ``session_id`` back on the next turn to carry context and
    avoid repeating already-shown restaurants.
    """
    _get_store(request)
    orchestrator = _get_orchestrator(request)
    return await orchestrator.recommend_chat(body)


@router.get("/meta", tags=["data"])
async def meta(request: Request) -> dict:
    """Filter options for the UI: available cities, localities, and cuisines."""
    store = _get_store(request)
    return {
        "cities": store.get_cities(),
        "localities": store.get_localities(),
        "cuisines": store.get_cuisines(),
        "default_city": settings.default_city,
        "restaurant_count": store.count(),
    }


@router.get("/health", tags=["ops"])
async def health(request: Request) -> dict:
    """Liveness / readiness probe with dataset and config status."""
    store = getattr(request.app.state, "restaurant_store", None)
    dataset_loaded = store is not None and store.count() > 0
    return {
        "status": "ok" if dataset_loaded else "degraded",
        "dataset_loaded": dataset_loaded,
        "restaurant_count": store.count() if store is not None else 0,
        "groq_configured": settings.groq_configured,
        "groq_model_intent": settings.groq_model_intent,
        "groq_model_rank": settings.groq_model_rank,
    }


@router.get("/restaurants/{restaurant_id}", response_model=Restaurant, tags=["data"])
async def get_restaurant(request: Request, restaurant_id: str) -> Restaurant:
    """Return a single restaurant by ID."""
    store = _get_store(request)
    restaurant = store.get_by_id(restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No restaurant '{restaurant_id}'."},
        )
    return restaurant
