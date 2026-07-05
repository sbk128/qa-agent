from typing import Literal

from pydantic import BaseModel, Field, computed_field

from src.models.finding import Finding
from src.models.testcase import TestCase

# What the agent actually observed when it ran (or tried to run) a case.
#   accepted / rejected — the form gave a real verdict we could read
#   error               — the case ran but broke (submit didn't fire, 5xx, a fill failed)
#   skipped             — the case never ran (site unresponsive, hang guard, nav failure)
Observed = Literal["accepted", "rejected", "error", "skipped"]

# The reportable status, derived from `observed` + the case's expectation:
#   pass    — ran and matched the expected verdict
#   review  — ran but did NOT match the expectation (worth a human look)
#   info    — ran, but the case had no oracle (expected="unknown") — informational only
#   error   — couldn't get a verdict
#   skipped — never ran
Status = Literal["pass", "review", "info", "error", "skipped"]


class TestResult(BaseModel):
    case: TestCase
    url: str = ""
    observed: Observed = "error"
    passed: bool = False
    detail: str = ""
    findings: list[Finding] = Field(default_factory=list)
    # Failed field-fills (selector -> reason). A non-empty map means we could NOT
    # put the case's data into the form, so the verdict is not trustworthy — the
    # runner turns any such case into observed="error" instead of judging it.
    fill_failures: dict[str, str] = Field(default_factory=dict)
    # Relative path (under the run's report dir) to a screenshot captured for a
    # non-passing case, so a human can verify the finding without re-running.
    screenshot_path: str | None = None

    @computed_field  # serialized into report.json / model_dump for the GUI + report
    @property
    def status(self) -> Status:
        if self.observed in ("error", "skipped"):
            return self.observed
        # observed is accepted/rejected here
        if self.case.expected == "unknown":
            return "info"          # no oracle — neither pass nor fail
        return "pass" if self.passed else "review"

    @property
    def is_pass(self) -> bool:
        return self.status == "pass"

    @property
    def counts_toward_score(self) -> bool:
        """True for cases that have a real pass/fail oracle (excludes info/error/skipped)."""
        return self.status in ("pass", "review")
