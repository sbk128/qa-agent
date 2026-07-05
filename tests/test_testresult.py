"""TestResult.status — the honesty layer over pass/fail."""
from __future__ import annotations

from src.models.testcase import TestCase
from src.models.testresult import TestResult


def _case(expected="rejected"):
    return TestCase(name="c", category="edge", description="d", expected=expected)


def test_pass_and_review():
    assert TestResult(case=_case(), observed="rejected", passed=True).status == "pass"
    assert TestResult(case=_case(), observed="accepted", passed=False).status == "review"


def test_unknown_expectation_is_info_not_pass():
    r = TestResult(case=_case("unknown"), observed="accepted", passed=False)
    assert r.status == "info"
    assert not r.counts_toward_score        # <- old code counted these as passed


def test_skipped_and_error_never_pass():
    assert TestResult(case=_case(), observed="skipped").status == "skipped"
    assert TestResult(case=_case(), observed="error").status == "error"
    assert not TestResult(case=_case(), observed="skipped").counts_toward_score
    assert not TestResult(case=_case(), observed="error").counts_toward_score


def test_status_is_serialized():
    # computed_field must appear in model_dump so the GUI/report see it.
    d = TestResult(case=_case(), observed="rejected", passed=True).model_dump()
    assert d["status"] == "pass"


def test_only_scored_cases_have_oracle():
    scored = TestResult(case=_case(), observed="rejected", passed=True)
    info = TestResult(case=_case("unknown"), observed="accepted")
    assert scored.counts_toward_score
    assert not info.counts_toward_score
