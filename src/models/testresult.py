from typing import Literal
from pydantic import BaseModel, Field
from src.models.testcase import TestCase
from src.models.finding import Finding

class TestResult(BaseModel):
    case: TestCase
    url: str = ""
    observed: Literal["accepted", "rejected", "error"] = "error"
    passed: bool = False
    detail: str = ""
    findings: list[Finding] = Field(default_factory=list)