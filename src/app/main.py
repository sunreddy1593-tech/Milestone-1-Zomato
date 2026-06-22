"""FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --app-dir src
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import AmbiguousQueryError, ServiceUnavailableError
from app.api.routes import router
from app.config import settings
from app.data.loader import RestaurantStore
from app.pipeline.orchestrator import Orchestrator
from app.retrieval.semantic import SemanticIndex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan — load dataset at startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the restaurant catalogue and build the pipeline before serving."""
    store = RestaurantStore.from_file(settings.data_file)
    app.state.restaurant_store = store
    # Build the semantic index once at startup (Phase 9.4) so the first request
    # isn't penalised; skipped when semantic search is disabled.
    semantic = SemanticIndex(store.get_all()) if settings.semantic_enabled else None
    app.state.orchestrator = Orchestrator(store, semantic_index=semantic)
    logger.info(
        "Loaded %d restaurants; orchestrator ready (semantic=%s)",
        store.count(),
        bool(semantic),
    )
    yield


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI-Powered Restaurant Recommendation System",
    description=(
        "Hybrid recommendation backend that combines deterministic retrieval "
        "with Groq-powered LLM ranking to return grounded, explainable "
        "restaurant suggestions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# ---------------------------------------------------------------------------
# Static frontend (Phase 8) — served at /ui, with a root redirect
# ---------------------------------------------------------------------------

_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():

    @app.get("/", include_in_schema=False)
    async def _root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="ui")
    logger.info("Serving frontend from %s at /ui", _FRONTEND_DIR)


# ---------------------------------------------------------------------------
# Error handling — map validation failures to the documented contract (§9.1)
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return 400 validation_error (or 422 for malformed JSON bodies)."""
    errors = exc.errors()
    is_malformed_json = any(e.get("type") == "json_invalid" for e in errors)
    details = [
        {
            "loc": list(e.get("loc", [])),
            "msg": e.get("msg", ""),
            "type": e.get("type", ""),
        }
        for e in errors
    ]
    if is_malformed_json:
        return JSONResponse(
            status_code=422,
            content={"error": "ambiguous_query", "message": "Malformed request body."},
        )
    return JSONResponse(
        status_code=400,
        content={"error": "validation_error", "details": details},
    )


@app.exception_handler(AmbiguousQueryError)
async def ambiguous_query_handler(
    request: Request, exc: AmbiguousQueryError
) -> JSONResponse:
    """Return 422 ambiguous_query with a helpful message."""
    return JSONResponse(
        status_code=422,
        content={"error": "ambiguous_query", "message": exc.message},
    )


@app.exception_handler(ServiceUnavailableError)
async def service_unavailable_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    """Return 503 service_unavailable."""
    return JSONResponse(
        status_code=503,
        content={"error": "service_unavailable", "message": exc.message},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Normalise HTTP errors to a top-level ``{"error": ...}`` envelope."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = detail
    else:
        content = {"error": "http_error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so unexpected errors never leak stack traces or crash workers."""
    logger.exception("Unhandled error processing %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"error": "internal_error"})
