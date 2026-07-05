"""End-to-end of the report renderer over a hand-built state."""
from __future__ import annotations

from src.models.finding import Finding
from src.models.testcase import TestCase
from src.models.testresult import TestResult
from src.reporting.report import build_report


def _result(name, expected, observed, passed, findings=None):
    return TestResult(
        case=TestCase(name=name, category="edge", description="d", expected=expected),
        url="http://app/form", observed=observed, passed=passed,
        findings=findings or [],
    )


def _state():
    return {
        "visited_urls": ["http://app/form"],
        "findings": [],
        "test_results": [
            _result("valid data", "accepted", "accepted", True),                 # pass
            _result("XSS in name", "rejected", "accepted", False,                 # review + worth
                    findings=[Finding(category="network_error", severity="medium",
                                      title="Failed", description="422 POST http://app/x")]),
            _result("free-text note", "unknown", "accepted", False),              # info
            _result("hung case", "rejected", "skipped", False),                   # skipped
        ],
    }


def test_header_counts_only_scored_cases():
    md = build_report(_state(), meta={"target": "http://app/form"})
    # 1 pass out of 2 scored (pass + review); info and skipped excluded.
    assert "1/2 checks behaved as expected" in md


def test_buckets_render():
    md = build_report(_state())
    assert "⚠ Worth checking  (1)" in md      # hard evidence (422)
    assert "Skipped  (1)" in md
    assert "Informational — no oracle  (1)" in md


def test_meta_block_present():
    md = build_report(_state(), meta={"target": "http://app/form", "provider": "groq",
                                      "model": "llama-3.3-70b", "allow_all": False})
    assert "## Run" in md
    assert "llama-3.3-70b" in md


def test_empty_state_is_safe():
    md = build_report({"visited_urls": [], "findings": [], "test_results": []})
    assert "# QA Test Report" in md
    assert "_No forms were tested._" in md
