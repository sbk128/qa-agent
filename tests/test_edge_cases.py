"""The static edge-case injector — one bad field at a time, free-text only."""
from __future__ import annotations

from conftest import make_element

from src.agent.testgen import _is_free_text, build_edge_cases


def test_free_text_detection():
    assert _is_free_text(make_element(tag="input", element_type="text"))
    assert not _is_free_text(make_element(tag="select"))
    assert not _is_free_text(make_element(widget_type="mui_select"))
    assert not _is_free_text(make_element(element_type="radio"))
    assert not _is_free_text(make_element(element_type="checkbox"))


def test_injects_only_into_free_text_fields():
    fields = [
        make_element(name="Email", selector="#email", semantic_kind="email"),
        make_element(name="Country", selector="#country", tag="select"),
    ]
    baseline = {"#email": "a@b.com", "#country": "India"}
    cases = build_edge_cases(fields, baseline)
    # Every generated case corrupts the email; none corrupt the (select) country.
    assert cases
    for c in cases:
        assert c.field_values["#country"] == "India"     # untouched baseline
        assert c.field_values["#email"] != "a@b.com"      # exactly this field corrupted
        assert c.expected == "rejected"
        assert c.category == "edge"


def test_one_bad_field_at_a_time():
    fields = [
        make_element(name="Email", selector="#email", semantic_kind="email"),
        make_element(name="Name", selector="#name", semantic_kind="name"),
    ]
    baseline = {"#email": "a@b.com", "#name": "Asha"}
    for c in build_edge_cases(fields, baseline):
        corrupted = [s for s, v in c.field_values.items() if v != baseline[s]]
        assert len(corrupted) == 1


def test_per_field_cap():
    fields = [make_element(name="Note", selector="#note", semantic_kind="unknown")]
    cases = build_edge_cases(fields, {"#note": "hi"})
    assert len(cases) <= 2      # _MAX_PER_FIELD
