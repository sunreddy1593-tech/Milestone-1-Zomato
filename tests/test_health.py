"""Phase 0/1 — health endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app


def test_health_returns_200_with_dataset_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dataset_loaded"] is True
    assert body["restaurant_count"] > 0
    assert body["groq_configured"] is settings.groq_configured
    assert body["groq_model_intent"] == settings.groq_model_intent
    assert body["groq_model_rank"] == settings.groq_model_rank


def test_no_hardcoded_secret_in_source_defaults() -> None:
    """The API key default in code must be empty (no secret committed in source).

    The runtime value may be populated from a local ``.env`` (git-ignored); we
    only assert the field *default* defined in ``config.py`` is blank.
    """
    assert Settings.model_fields["groq_api_key"].default == ""


def test_settings_have_expected_defaults() -> None:
    """Non-secret defaults are stable regardless of .env presence."""
    assert settings.groq_model_intent == "llama-3.1-8b-instant"
    assert settings.groq_model_rank == "llama-3.3-70b-versatile"
    assert settings.default_city == "Bengaluru"
    assert settings.max_candidates == 50
    assert settings.timezone == "Asia/Kolkata"
