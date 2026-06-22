"""LLM client protocol — decouples pipeline logic from provider SDK details."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Minimal async interface for structured JSON completions."""

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
        """Return parsed JSON from the model response.

        Raises on unrecoverable provider or parse errors after retries.
        """
        ...
