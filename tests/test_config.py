"""AppConfig defaults and the YAML loader."""
from __future__ import annotations

from pathlib import Path

from src.config import AppConfig, load_config

_EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "example.yaml"


def test_defaults_are_safe():
    c = AppConfig()
    assert c.allow_all is False              # safety ON by default
    assert c.max_iterations == 12
    assert "/logout" in c.all_blocked_url_patterns()


def test_blocked_url_dedup():
    c = AppConfig(blocked_url_patterns=["/logout", "/custom"])
    pats = c.all_blocked_url_patterns()
    assert pats.count("/logout") == 1        # default + config don't duplicate
    assert "/custom" in pats


def test_load_example_yaml():
    c = load_config(_EXAMPLE)
    assert c.url == "https://example.com"
    assert c.provider == "groq"
    assert c.allow_all is False              # policy "block" -> gate on
    assert c.block_uncertain is True
    assert "delete account" in c.blocked_button_text
    assert "/billing/charge" in c.all_blocked_url_patterns()


def test_policy_allow_maps_to_sandbox(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "target:\n  url: http://x\n"
        "safety:\n  destructive_action_policy: allow\n",
        encoding="utf-8",
    )
    c = load_config(p)
    assert c.allow_all is True
    assert c.block_uncertain is False
