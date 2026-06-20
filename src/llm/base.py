"""LLMProvider Protocol — providers are interchangeable via env var."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    async def text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str: ...

    async def structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> BaseModel: ...
