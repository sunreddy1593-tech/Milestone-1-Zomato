"""Groq SDK implementation of :class:`LLMClient`."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from groq import AsyncGroq, RateLimitError
from groq import APIError as GroqAPIError

from app.config import settings
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)

_JSON_REPAIR_SUFFIX = (
    "\n\nYour previous response was not valid JSON. "
    "Return ONLY a single valid JSON object matching the requested schema."
)


class GroqClientError(Exception):
    """Raised when Groq returns an unrecoverable error."""


class GroqClient:
    """Async Groq wrapper with JSON output and parse retries."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout_seconds: int | None = None,
        client: AsyncGroq | None = None,
        max_rate_limit_retries: int = 2,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        key = api_key if api_key is not None else settings.groq_api_key
        self._default_model = default_model or settings.groq_model_intent
        self._timeout = timeout_seconds or settings.groq_timeout_seconds
        self._client = client or AsyncGroq(api_key=key)
        self._max_rate_limit_retries = max_rate_limit_retries
        self._backoff_base = backoff_base_seconds

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
        """Call Groq chat completions and parse JSON from the response."""
        chosen_model = model or self._default_model
        prompt = user_prompt
        last_decode_error: json.JSONDecodeError | None = None

        for attempt in range(max_retries + 1):
            raw = await self._call_with_resilience(
                system_prompt=system_prompt,
                user_prompt=prompt,
                model=chosen_model,
                temperature=temperature,
            )
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                last_decode_error = exc
                logger.warning(
                    "Groq JSON parse failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                if attempt < max_retries:
                    prompt = user_prompt + _JSON_REPAIR_SUFFIX
                    continue

        assert last_decode_error is not None
        raise GroqClientError(
            f"Groq returned invalid JSON after {max_retries + 1} attempt(s)"
        ) from last_decode_error

    async def _call_with_resilience(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        """Invoke Groq with timeout handling and 429/5xx exponential backoff."""
        for rl_attempt in range(self._max_rate_limit_retries + 1):
            try:
                return await asyncio.wait_for(
                    self._create_completion(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=model,
                        temperature=temperature,
                    ),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError as exc:
                raise GroqClientError(
                    f"Groq request timed out after {self._timeout}s"
                ) from exc
            except RateLimitError as exc:
                if rl_attempt < self._max_rate_limit_retries:
                    await self._backoff(rl_attempt, reason="rate limit (429)")
                    continue
                raise GroqClientError("Groq rate limit exceeded") from exc
            except GroqAPIError as exc:
                status = getattr(exc, "status_code", None)
                if (
                    status is not None
                    and 500 <= status < 600
                    and rl_attempt < self._max_rate_limit_retries
                ):
                    await self._backoff(rl_attempt, reason=f"server error ({status})")
                    continue
                raise GroqClientError(f"Groq API error: {exc}") from exc

        raise GroqClientError("Groq call failed after retries")

    async def _backoff(self, attempt: int, *, reason: str) -> None:
        delay = self._backoff_base * (2**attempt)
        logger.warning("Groq %s; backing off %.2fs before retry", reason, delay)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _create_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise GroqClientError("Groq returned empty completion content")
        return content


def build_groq_client(
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> GroqClient | None:
    """Return a configured client, or ``None`` when no API key is available."""
    key = api_key if api_key is not None else settings.groq_api_key
    if not key:
        return None
    return GroqClient(api_key=key, default_model=model or settings.groq_model_intent)
