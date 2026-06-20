from src.browser.session import PageSummary
from src.llm import LLMProvider
from src.models.context import InferredContext
from src.models.element import Element


def build_context_blob(summary: PageSummary, elements: list[Element]) -> str:
    # A compact, LLM-friendly description of the page: the Phase 0 summary
    # plus a sample of the visible interactive elements.
    field_lines = [
        f"- {e.tag} {e.semantic_kind}: {e.name}"
        for e in elements
        if e.visible
    ][:25]  # cap the sample so we stay well under the token budget
    return (
        summary.to_prompt()
        + "\n\nInteractive elements (sample):\n"
        + "\n".join(field_lines)
    )


async def infer_context(llm: LLMProvider, blob: str) -> InferredContext:
    prompt = (
        "You are analyzing a web page to infer its context. "
        "Based on the page description below, determine the language, "
        "country, currency, domain type, whether the user appears logged in, "
        "and the app type. Infer the country from visible currency symbols, "
        "phone/address formats, language, and any localized text. "
        "Always output a concrete ISO 3166 alpha-2 country code (e.g. 'US', 'IN', 'GB') "
        "for country_hint — never leave it null. For the other fields, use sensible "
        "defaults when unsure.\n\n"
        f"{blob}"
    )
    result = await llm.structured(prompt, InferredContext)
    return result