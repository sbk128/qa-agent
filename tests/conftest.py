"""Shared test helpers."""
from __future__ import annotations

from src.models.element import Element
from src.models.safety import SafetyVerdict


def make_element(**kw) -> Element:
    """Element with sensible defaults; override any field via kwargs."""
    base = dict(tag="input", name="Field", selector="#f", element_type="text")
    base.update(kw)
    return Element(**base)


class FakeLLM:
    """Minimal LLMProvider stand-in. `structured` returns a queued/fixed value and
    counts calls so tests can assert caching / no-network behaviour."""

    def __init__(self, verdict: SafetyVerdict | None = None) -> None:
        self.calls = 0
        self._verdict = verdict or SafetyVerdict(risk="uncertain", reason="fake")

    async def text(self, prompt, **kw) -> str:
        self.calls += 1
        return "ok"

    async def structured(self, prompt, schema, **kw):
        self.calls += 1
        return self._verdict
