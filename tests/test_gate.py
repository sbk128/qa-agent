"""The safety gate — word-boundary matching, caching, policy."""
from __future__ import annotations

from conftest import FakeLLM, make_element

from src.models.safety import SafetyVerdict
from src.safety.gate import SafetyGate, url_is_blocked, word_match
from src.safety.patterns import DESTRUCTIVE


def test_word_match_ignores_substrings():
    # The original bug: substring matching flagged benign labels.
    assert word_match("Display options", DESTRUCTIVE) is None
    assert word_match("Dropdown", DESTRUCTIVE) is None
    assert word_match("Removed items", DESTRUCTIVE) is None
    assert word_match("Payments report", DESTRUCTIVE) is None


def test_word_match_catches_real_danger():
    assert word_match("Pay now", DESTRUCTIVE) == "pay"
    assert word_match("Delete account", DESTRUCTIVE) == "delete"
    assert word_match("Drop table", DESTRUCTIVE) == "drop"
    assert word_match("Cancel subscription", DESTRUCTIVE) == "cancel subscription"


def test_url_is_blocked():
    assert url_is_blocked("http://x/app/logout", ["/logout"]) == "/logout"
    assert url_is_blocked("http://x/BILLING/Charge", ["/billing/charge"]) == "/billing/charge"
    assert url_is_blocked("http://x/home", ["/logout"]) is None


async def test_gate_blocks_destructive():
    gate = SafetyGate(FakeLLM())
    v = await gate.evaluate(make_element(tag="button", name="Delete user"))
    assert v.risk == "destructive"
    assert gate.should_block(v)


async def test_gate_allows_create_prefix():
    # "Add Payment" contains "pay" but is a data-entry action.
    gate = SafetyGate(FakeLLM())
    v = await gate.evaluate(make_element(tag="button", name="Add Payment"))
    assert v.risk == "safe"


async def test_gate_caches_llm_verdicts():
    llm = FakeLLM(SafetyVerdict(risk="uncertain", reason="fake"))
    gate = SafetyGate(llm)
    # "Submit" is ambiguous -> escalated to the LLM, but only once for the same label.
    await gate.evaluate(make_element(tag="button", name="Submit"))
    await gate.evaluate(make_element(tag="button", name="Submit"))
    await gate.evaluate(make_element(tag="button", name="Submit"))
    assert llm.calls == 1


async def test_gate_allow_all_disables():
    gate = SafetyGate(FakeLLM(), allow_all=True)
    v = await gate.evaluate(make_element(tag="button", name="Delete everything"))
    assert v.risk == "safe" and not gate.should_block(v)


async def test_gate_block_uncertain_policy():
    llm = FakeLLM(SafetyVerdict(risk="uncertain", reason="fake"))
    strict = SafetyGate(llm, block_uncertain=True)
    v = await strict.evaluate(make_element(tag="button", name="Proceed"))
    assert strict.should_block(v)          # uncertain is blocked under this policy
    lenient = SafetyGate(FakeLLM(SafetyVerdict(risk="uncertain")))
    v2 = await lenient.evaluate(make_element(tag="button", name="Proceed"))
    assert not lenient.should_block(v2)     # default policy lets uncertain through


async def test_gate_extra_blocked_from_config():
    gate = SafetyGate(FakeLLM(), extra_blocked=("mark paid",))
    v = await gate.evaluate(make_element(tag="button", name="Mark Paid"))
    assert v.risk == "destructive"
