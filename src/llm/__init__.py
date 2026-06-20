"""LLM provider abstraction. Swap providers via the LLM_PROVIDER env var."""
from __future__ import annotations

import os

from .base import LLMProvider
from .groq_provider import DEFAULT_MODEL, SMALL_MODEL, GroqProvider


def get_provider() -> LLMProvider:
    name = os.environ.get("LLM_PROVIDER", "groq").lower()
    if name == "groq":
        return GroqProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {name!r}")


__all__ = [
    "DEFAULT_MODEL",
    "SMALL_MODEL",
    "GroqProvider",
    "LLMProvider",
    "get_provider",
]
