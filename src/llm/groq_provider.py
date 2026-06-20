"""Groq-backed LLMProvider with retry, JSON mode, and rate-limit backoff."""
from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

import structlog
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)

# Model IDs are pinned here so callers can pick "big" vs "small" without
# remembering the exact Groq slugs.
DEFAULT_MODEL = "llama-3.3-70b-versatile"
SMALL_MODEL = "llama-3.1-8b-instant"


class GroqProvider:
    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_MODEL,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to .env or export it."
            )
        self._client = AsyncGroq(api_key=key)
        self._default_model = default_model
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await self._call(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()

    async def structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> BaseModel:
        json_schema = schema.model_json_schema()
        sys_msg = (
            (system + "\n\n" if system else "")
            + "Respond with a single JSON object that matches this JSON schema. "
            + "Do not wrap it in markdown.\n"
            + json.dumps(json_schema)
        )
        resp = await self._call(
            model=model or self._default_model,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return schema.model_validate_json(raw)
        except ValidationError:
            log.error("groq.structured.invalid_json", raw=raw)
            raise

    async def _call(self, **kwargs: Any):
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except RateLimitError as e:
                delay = self._retry_after(e) or self._backoff(attempt)
                log.warning(
                    "groq.rate_limited", attempt=attempt, sleep_s=round(delay, 2)
                )
                await asyncio.sleep(delay)
                last_err = e
            except (APIConnectionError, APITimeoutError, APIStatusError) as e:
                delay = self._backoff(attempt)
                log.warning(
                    "groq.transient_error",
                    attempt=attempt,
                    sleep_s=round(delay, 2),
                    error=str(e),
                )
                await asyncio.sleep(delay)
                last_err = e
        raise RuntimeError(
            f"Groq call failed after {self._max_retries} retries"
        ) from last_err

    def _backoff(self, attempt: int) -> float:
        base = min(self._base_delay * (2**attempt), self._max_delay)
        return base + random.uniform(0, base * 0.1)

    @staticmethod
    def _retry_after(err: RateLimitError) -> float | None:
        try:
            value = err.response.headers.get("retry-after")
            return float(value) if value else None
        except Exception:
            return None
