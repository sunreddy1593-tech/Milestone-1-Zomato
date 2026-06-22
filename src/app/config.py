"""Application configuration — loads settings from environment / .env file.

Uses pydantic-settings so every value can be overridden via environment
variables or a `.env` file at the project root.
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root is three levels up from this file:
#   src/app/config.py -> src/app -> src -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Centralised application settings.

    Every field maps 1-to-1 with an environment variable (case-insensitive).
    See `.env.example` for documentation of each variable.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",            # don't fail on unrelated env vars
    )

    # --- Groq LLM Provider ---
    groq_api_key: str = ""
    groq_model_intent: str = "llama-3.1-8b-instant"
    groq_model_rank: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: int = 30

    # --- Data ---
    data_path: str = "data/restaurants.json"

    # --- Defaults ---
    default_city: str = "Bengaluru"
    max_candidates: int = 50
    # How many pre-ranked candidates to actually send to the LLM ranker.
    # Kept below `max_candidates` to stay within provider tokens-per-minute
    # limits; the remaining candidates are still used for deterministic backfill.
    llm_rank_candidates: int = 20
    default_top_n: int = 5

    # --- Timezone ---
    timezone: str = "Asia/Kolkata"

    # --- Phase 9: Stretch features ---
    # Response caching
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 256
    # Lightweight semantic pre-rank (dependency-free TF-IDF cosine)
    semantic_enabled: bool = True
    semantic_weight: float = 0.35  # blend vs rating when reordering candidates
    # Conversational sessions
    session_ttl_seconds: int = 1800
    session_max_entries: int = 512
    # Personalization
    personalization_enabled: bool = True

    # --- Server ---
    port: int = 8000

    # --- Derived helpers (not env-backed) ---
    @property
    def groq_configured(self) -> bool:
        """Return True when a non-empty Groq API key is set."""
        return bool(self.groq_api_key)

    @property
    def data_file(self) -> Path:
        """Resolve ``data_path`` relative to the project root."""
        p = Path(self.data_path)
        if p.is_absolute():
            return p
        return _PROJECT_ROOT / p


# Module-level singleton — importable everywhere as:
#     from app.config import settings
settings = Settings()
