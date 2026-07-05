from typing import Literal

from pydantic import BaseModel


class TestCase(BaseModel):
    name: str
    category: Literal["happy", "edge", "scenario"]
    description: str
    field_values: dict[str, str] = {}
    expected: Literal["accepted", "rejected", "unknown"] = "unknown"
    rationale: str = ""

class TestSuite(BaseModel):
    cases: list[TestCase] = []
    