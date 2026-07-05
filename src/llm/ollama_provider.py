"""Ollama-backed LLMProvider — a local mirror of GroqProvider.

Talks to a locally running Ollama server (default http://localhost:11434) over
its native `/api/chat` endpoint. Mirrors GroqProvider's surface exactly:

  - text()       — plain completion
  - structured() — JSON that validates against a Pydantic schema
  - retry/backoff on transient network errors

Two deliberate differences from Groq, both because this is a single local model:
  - The `model` kwarg is accepted (Protocol parity) but ignored — there is one
    configured local model, and callers that pass a Groq slug like
    "llama-3.1-8b-instant" (the safety gate's SMALL_MODEL) must not break.
  - For structured(), we hand Ollama the JSON *schema* as `format` (its
    "structured outputs" mode), which constrains generation to valid JSON. Small
    models are far more reliable this way. If the server rejects the schema we
    fall back to `format="json"` with the schema described in the prompt — the
    same approach GroqProvider uses.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)

# The model installed on this box (`ollama list`). Override with OLLAMA_MODEL.
DEFAULT_MODEL = "gemma4:e4b"
SMALL_MODEL = DEFAULT_MODEL  # no separate small model locally — reuse the one.

DEFAULT_BASE_URL = "http://localhost:11434"

# Local generation is slow compared to Groq's LPU, so give reads plenty of room.
_TIMEOUT = httpx.Timeout(600.0, connect=10.0)


class OllamaProvider:
    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 20.0,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self._default_model = (
            default_model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        )
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        # Ollama's default context is small (~4k tokens). The test-case suite is a
        # large structured output (a 45-case suite is ~12k tokens) and silently
        # truncates mid-JSON at the default — the model isn't failing, it just runs
        # out of room. Give it a big window; num_predict=-1 = don't cap the output.
        self._num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
        self._num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "-1"))
        # Named `_client` so the GUI's RunWorker._aclose_llm can aclose() it.
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)

    async def text(
        self,
        prompt: str,
        *,
        model: str | None = None,  # accepted for parity; see module docstring.
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        data = await self._chat(messages=messages, temperature=temperature)
        return (data.get("message", {}).get("content") or "").strip()

    async def structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,  # accepted for parity; see module docstring.
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
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        # First choice: hand Ollama the schema as `format` (structured outputs).
        # This constrains decoding to schema-valid JSON — a big win for small
        # models. If the server can't compile it, fall back to plain JSON mode.
        fmt: Any = json_schema
        last_err: ValidationError | None = None
        for attempt in range(2):
            try:
                data = await self._chat(messages=messages, temperature=temperature, fmt=fmt)
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 400:
                    log.warning("ollama.schema_format_rejected.fallback_json")
                    fmt = "json"
                    data = await self._chat(messages=messages, temperature=temperature, fmt=fmt)
                else:
                    raise

            raw = data.get("message", {}).get("content") or "{}"
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                # One corrective retry, feeding the validation error back to the model.
                last_err = e
                log.warning("ollama.structured.invalid_json", attempt=attempt)
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content":
                        f"That did not match the schema: {str(e)[:500]}. "
                        "Return ONLY a corrected JSON object."},
                ]
        log.error("ollama.structured.invalid_json.final")
        raise last_err  # type: ignore[misc]

    async def _chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        fmt: Any | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._default_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": self._num_ctx,
                "num_predict": self._num_predict,
            },
        }
        if fmt is not None:
            body["format"] = fmt
        return await self._call(body)

    async def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post("/api/chat", json=body)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # 4xx (e.g. bad `format`) is a caller problem — surface it so
                # structured()'s fallback can react. Retry only on 5xx.
                if e.response is not None and e.response.status_code < 500:
                    raise
                delay = self._backoff(attempt)
                log.warning(
                    "ollama.server_error", attempt=attempt, sleep_s=round(delay, 2)
                )
                await asyncio.sleep(delay)
                last_err = e
            except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as e:
                delay = self._backoff(attempt)
                log.warning(
                    "ollama.transient_error",
                    attempt=attempt,
                    sleep_s=round(delay, 2),
                    error=str(e),
                )
                await asyncio.sleep(delay)
                last_err = e
        raise RuntimeError(
            f"Ollama call failed after {self._max_retries} retries. "
            f"Is `ollama serve` running at {self._base_url}?"
        ) from last_err

    def _backoff(self, attempt: int) -> float:
        base = min(self._base_delay * (2**attempt), self._max_delay)
        return base + random.uniform(0, base * 0.1)
