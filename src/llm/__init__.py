"""LLM provider abstraction. Swap providers via the LLM_PROVIDER env var."""
from __future__ import annotations

import os

from .base import LLMProvider
from .groq_provider import DEFAULT_MODEL, SMALL_MODEL, GroqProvider
from .ollama_provider import OllamaProvider


def get_provider(name: str | None = None) -> LLMProvider:
    """Return the configured LLM provider.

    `name` wins when given (the GUI passes the user's dropdown choice);
    otherwise fall back to the LLM_PROVIDER env var, defaulting to groq.
    """
    name = (name or os.environ.get("LLM_PROVIDER", "groq")).lower()
    if name == "groq":
        return GroqProvider()
    if name == "ollama":
        return OllamaProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {name!r}")


__all__ = [
    "DEFAULT_MODEL",
    "SMALL_MODEL",
    "GroqProvider",
    "OllamaProvider",
    "LLMProvider",
    "get_provider",
]
