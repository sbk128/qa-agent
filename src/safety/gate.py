"""Decides whether an action (a button click, a navigation) is safe to perform.

Two layers:
  - `word_match` / `SafetyGate.evaluate` — classify a button label.
  - `url_is_blocked` — reject a URL before the crawler navigates to it.

Label matching is word-boundary based, so "Pay now" is caught but "Display" is not.
Ambiguous labels ("Submit") are escalated to a small LLM, and every verdict is
CACHED by label so a 40-case run doesn't classify "Submit" 40 times.
"""
from __future__ import annotations

import re

from src.llm import SMALL_MODEL, LLMProvider
from src.models.element import Element
from src.models.safety import SafetyVerdict
from src.safety.patterns import AMBIGUOUS, DESTRUCTIVE

# Buttons that START with one of these are data-entry/create actions — safe to click
# even if the label contains a "destructive" word. e.g. "Add Payment" / "Save Charge"
# are recording data, not the irreversible "Pay now" / "Charge card" the rules target.
_SAFE_CREATE_PREFIXES = ("add ", "create ", "new ", "save ", "register ", "update ", "edit ")


def _compile(terms: tuple[str, ...]) -> re.Pattern[str]:
    # \b(?:pay|cancel subscription|...)\b — word boundaries around each alternative so
    # "pay" matches "Pay now" but not "Display", and "drop" not "Dropdown".
    alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)


_DESTRUCTIVE_RE = _compile(DESTRUCTIVE)
_AMBIGUOUS_RE = _compile(AMBIGUOUS)


def word_match(text: str, terms: tuple[str, ...]) -> str | None:
    """Return the first whole-word/phrase in `terms` found in `text`, else None."""
    m = _compile(terms).search(text or "")
    return m.group(0).lower() if m else None


def url_is_blocked(url: str, patterns) -> str | None:
    """Return the first blocked pattern that appears in `url` (case-insensitive), else None."""
    low = (url or "").lower()
    for p in patterns:
        if p and p.lower() in low:
            return p
    return None


class SafetyGate:
    def __init__(
        self,
        llm: LLMProvider,
        allow_all: bool = False,
        block_uncertain: bool = False,
        extra_blocked: tuple[str, ...] = (),
    ) -> None:
        self.llm = llm
        # Sandbox mode: skip the destructive block entirely. For dev/test targets where
        # exercising every action (incl. financial submits) is the point. Off by default.
        self.allow_all = allow_all
        # When True, an LLM "uncertain" verdict is treated as block-worthy by callers.
        self.block_uncertain = block_uncertain
        # Extra destructive words from the run config (safety.blocked_button_text_patterns).
        self._extra_re = _compile(tuple(extra_blocked)) if extra_blocked else None
        # label -> verdict, so repeated identical labels cost one classification.
        self._cache: dict[str, SafetyVerdict] = {}

    def should_block(self, verdict: SafetyVerdict) -> bool:
        """Policy applied by callers to a verdict."""
        if verdict.risk == "destructive":
            return True
        return self.block_uncertain and verdict.risk == "uncertain"

    async def evaluate(self, element: Element) -> SafetyVerdict:
        if self.allow_all:
            return SafetyVerdict(risk="safe", reason="sandbox mode (--allow-all): gate disabled")

        text = (element.name or "").lower().strip()
        if text in self._cache:
            return self._cache[text]

        verdict = await self._classify(text, element)
        self._cache[text] = verdict
        return verdict

    async def _classify(self, text: str, element: Element) -> SafetyVerdict:
        if self._extra_re is not None and self._extra_re.search(text):
            return SafetyVerdict(
                risk="destructive",
                reason="matched a config-blocked label",
                signals=["config"],
            )

        if text.startswith(_SAFE_CREATE_PREFIXES):
            return SafetyVerdict(risk="safe", reason="create/data-entry action")

        hit = word_match(text, DESTRUCTIVE)
        if hit:
            return SafetyVerdict(
                risk="destructive",
                reason=f"Text matched danger word: {hit!r}",
                signals=[f"text:{hit}"],
            )

        if word_match(text, AMBIGUOUS):
            return await self._ask_llm(element)

        return SafetyVerdict(risk="safe", reason="No destructive signals")

    async def _ask_llm(self, element: Element) -> SafetyVerdict:
        # NOTE: element.name is page-derived text. It is quoted and framed as data, but a
        # hostile page could still attempt prompt injection here — acceptable for the
        # internal/dev targets this tool is aimed at; revisit before pointing at untrusted UIs.
        prompt = (
            "You classify whether a UI action is safe for an autonomous web-testing "
            "agent to click. Choose exactly one risk level:\n"
            "- destructive: clearly causes irreversible data loss, financial charges, "
            "or messages to real people (e.g. 'Delete account', 'Pay now', 'Send invite').\n"
            "- safe: clearly harmless (navigation, search, or submitting/saving an "
            "ordinary form during testing).\n"
            "- uncertain: you cannot tell from the label alone, or it depends on "
            "context you can't see.\n"
            "Only choose 'destructive' when the danger is clear from the label itself. "
            "If you are unsure, choose 'uncertain' — never 'destructive'.\n"
            f"Action label: {element.name!r}\n"
            "Return the risk and a one-sentence reason."
        )
        return await self.llm.structured(prompt, SafetyVerdict, model=SMALL_MODEL)
