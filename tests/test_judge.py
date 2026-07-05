"""The judge — accepted / rejected / error, scoped to the app's own responses."""
from __future__ import annotations

from src.agent.runner import TestRunner
from src.models.action import ActionResult
from src.models.finding import Finding

_ok = ActionResult(action="click", selector="#submit", ok=True)
_failed_click = ActionResult(action="click", selector="#submit", ok=False)


def _judge(click=_ok, findings=None, responses=()):
    return TestRunner._judge(click, findings or [], responses)


def test_no_click_is_error():
    assert _judge(click=None) == "error"
    assert _judge(click=_failed_click) == "error"


def test_5xx_is_error_not_rejection():
    assert _judge(responses=[{"status": 500}]) == "error"


def test_4xx_is_rejection():
    assert _judge(responses=[{"status": 422}]) == "rejected"
    assert _judge(responses=[{"status": 400}]) == "rejected"


def test_client_validation_is_rejection():
    assert _judge(findings=[Finding(category="validation", title="bad")]) == "rejected"


def test_silence_is_accepted():
    assert _judge() == "accepted"
    assert _judge(responses=[{"status": 200}]) == "accepted"


def test_only_app_responses_reach_the_judge():
    # The runner passes app_responses already host-filtered, so an analytics 404 that
    # was excluded upstream simply isn't here — the submit reads as accepted.
    assert _judge(responses=[{"status": 200}]) == "accepted"
