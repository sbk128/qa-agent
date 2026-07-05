import operator
from typing import Annotated, TypedDict

from src.browser.session import PageSummary
from src.models.context import InferredContext
from src.models.element import Element
from src.models.finding import Finding
from src.models.testcase import TestCase
from src.models.testresult import TestResult


class AgentState(TypedDict, total=False):
    seed_url: str
    current_url: str
    summary: PageSummary
    elements: list[Element]
    context: InferredContext
    links: list[str]
    next_url: str | None
    frontier: list[str]
    iteration: int
    visited_urls: Annotated[list[str], operator.add]
    findings: Annotated[list[Finding], operator.add]
    test_cases: list[TestCase]
    test_results: Annotated[list[TestResult], operator.add]
    locale: str | None
