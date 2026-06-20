"""Phase 0 LangGraph: open a URL, screenshot it, ask the LLM to describe it."""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.browser import BrowserSession, PageSummary
from src.llm import get_provider


class Phase0State(TypedDict, total=False):
    url: str
    summary: PageSummary
    description: str
    screenshot_path: str


async def describe_node(state: Phase0State) -> Phase0State:
    llm = get_provider()
    async with BrowserSession() as session:
        await session.goto(state["url"])
        summary = await session.summary()
        shot = await session.screenshot("screenshots/phase0.png")

    description = await llm.text(
        prompt=(
            "Describe the following web page in exactly one sentence. "
            "Be specific about what the page is for.\n\n"
            f"{summary.to_prompt()}"
        ),
        temperature=0.0,
    )
    return {
        "summary": summary,
        "description": description,
        "screenshot_path": str(shot),
    }


def build_graph():
    graph = StateGraph(Phase0State)
    graph.add_node("describe", describe_node)
    graph.set_entry_point("describe")
    graph.add_edge("describe", END)
    return graph.compile()
