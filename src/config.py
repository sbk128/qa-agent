"""Typed run configuration + a loader for the YAML config that drives a run.

`AppConfig` is the single object passed into `build_agent_graph`; the CLI, the
GUI, and the demo scripts all construct one (from YAML, from argparse, or from
the GUI form) so there is exactly one place that defines what a run can be told
to do. The old code mutated a module-level `MAX_ITERATIONS` global instead —
this replaces that.

The YAML schema mirrors `configs/example.yaml` (nested: target / auth / scope /
safety / testing / output). `load_config` flattens it into `AppConfig`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Applied to any URL before it is crawled AND to launcher/submit labels. These are
# the always-on floor; a config's `blocked_url_patterns` extends them.
DEFAULT_BLOCKED_URL_PATTERNS: tuple[str, ...] = (
    "/logout", "/log-out", "/signout", "/sign-out", "/logoff",
)


class AppConfig(BaseModel):
    # --- target ---
    url: str | None = None
    routes: list[str] = Field(default_factory=list)   # extra pages to seed the frontier
    locale: str | None = None

    # --- llm ---
    provider: str = "groq"                            # "groq" | "ollama"

    # --- browser ---
    headless: bool = True

    # --- scope ---
    max_iterations: int = 12                          # crawl-lap cap
    allowed_domains: list[str] = Field(default_factory=list)  # empty = seed host only

    # --- safety ---
    allow_all: bool = False                           # sandbox: disable the destructive gate
    block_uncertain: bool = False                     # also block LLM-"uncertain" clicks
    blocked_url_patterns: list[str] = Field(default_factory=list)
    blocked_button_text: list[str] = Field(default_factory=list)

    # --- auth ---
    auth_path: str | None = None

    # --- output ---
    report_dir: str = "reports"
    capture_screenshots: bool = True                  # screenshot every non-passing case
    capture_trace: bool = False                       # Playwright trace.zip for the run

    def all_blocked_url_patterns(self) -> list[str]:
        """Config patterns plus the always-on defaults, de-duplicated."""
        seen: dict[str, None] = {}
        for p in (*DEFAULT_BLOCKED_URL_PATTERNS, *self.blocked_url_patterns):
            seen.setdefault(p.lower(), None)
        return list(seen)


def _get(d: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = d or {}
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default


def load_config(path: str | Path) -> AppConfig:
    """Load a nested YAML config (see configs/example.yaml) into an AppConfig."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    auth_mode = _get(raw, "auth", "mode", default="none")
    auth_path = _get(raw, "auth", "storage_state_path") if auth_mode == "storage_state" else None

    policy = _get(raw, "safety", "destructive_action_policy", default="block")

    return AppConfig(
        url=_get(raw, "target", "url"),
        routes=_get(raw, "target", "routes", default=[]) or [],
        locale=_get(raw, "target", "locale"),
        provider=_get(raw, "llm", "provider", default="groq") or "groq",
        headless=bool(_get(raw, "browser", "headless", default=True)),
        max_iterations=int(_get(raw, "scope", "max_iterations", default=12) or 12),
        allowed_domains=_get(raw, "scope", "allowed_domains", default=[]) or [],
        allow_all=(policy == "allow"),
        block_uncertain=(policy == "block"),
        blocked_url_patterns=_get(raw, "safety", "blocked_url_patterns", default=[]) or [],
        blocked_button_text=_get(raw, "safety", "blocked_button_text_patterns", default=[]) or [],
        auth_path=auth_path,
        report_dir=_get(raw, "output", "report_dir", default="reports") or "reports",
        capture_screenshots=bool(_get(raw, "output", "screenshots", default=True)),
        capture_trace=bool(_get(raw, "output", "trace", default=False)),
    )
