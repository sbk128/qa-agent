"""Pure helpers in the executor: submit detection, date coercion, placeholders."""
from __future__ import annotations

from conftest import make_element

from src.agent.executor import _is_placeholder, _to_iso_date, find_submit


def test_to_iso_date_formats():
    assert _to_iso_date("2026-07-04") == "2026-07-04"
    assert _to_iso_date("04/07/2026") == "2026-07-04"      # day-first (Indian locale)
    assert _to_iso_date("July 4, 2026") == "2026-07-04"
    # Unknown format is returned unchanged so page.fill fails loudly.
    assert _to_iso_date("not a date") == "not a date"


def test_is_placeholder():
    assert _is_placeholder("Select a country")
    assert _is_placeholder("-- choose --")
    assert not _is_placeholder("India")


def test_find_submit_prefers_typed_submit_in_form():
    els = [
        make_element(tag="input", element_type="text", name="Name", in_form=True),
        make_element(tag="button", element_type="button", name="Cancel", in_form=True),
        make_element(tag="button", element_type="submit", name="Go", in_form=True, selector="#go"),
    ]
    assert find_submit(els).selector == "#go"


def test_find_submit_matches_label_words():
    els = [
        make_element(tag="button", element_type="button", name="Register", in_form=True, selector="#reg"),
    ]
    assert find_submit(els).selector == "#reg"


def test_find_submit_skips_disabled_and_invisible():
    els = [
        make_element(tag="button", element_type="submit", name="Save", in_form=True,
                     disabled=True, selector="#disabled"),
        make_element(tag="button", element_type="submit", name="Save", in_form=True,
                     visible=False, selector="#hidden"),
    ]
    assert find_submit(els) is None


def test_find_submit_returns_none_when_nothing_clickable():
    els = [make_element(tag="input", element_type="text", name="Name")]
    assert find_submit(els) is None
