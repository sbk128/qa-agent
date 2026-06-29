"""Filesystem + environment helpers shared across the GUI.

Everything is resolved relative to the project root (the `qa-agent/` folder that
contains `src/`), so the GUI behaves the same no matter where it's launched from.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# gui/paths.py -> gui/ -> qa-agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_AUTH = PROJECT_ROOT / "auth.json"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_LOCAL_FILE = PROJECT_ROOT / ".env.local"


def load_env() -> None:
    """Load `.env` then `.env.local` (local overrides), matching the CLI scripts."""
    load_dotenv(ENV_FILE)
    load_dotenv(ENV_LOCAL_FILE, override=True)


def groq_key_present() -> bool:
    """True if a GROQ API key is available in the environment."""
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


def has_saved_session(path: Path | str) -> bool:
    """Mirror of show_agent.py's `_has_session`: a real session has a cookie or
    a localStorage origin (an empty `auth.json` would otherwise silently skip auth)."""
    import json

    p = Path(path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except Exception:
        return False
    return bool(data.get("cookies") or data.get("origins"))


def set_env_value(key: str, value: str) -> None:
    """Upsert a KEY=value line into `.env.local` (gitignored) and the live env.

    We write to `.env.local` rather than `.env` on purpose — it's the repo's
    convention for machine-local secrets and it's already gitignored, so a key
    typed into the Settings dialog never lands in a committed file.
    """
    lines: list[str] = []
    if ENV_LOCAL_FILE.exists():
        lines = ENV_LOCAL_FILE.read_text().splitlines()

    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

    ENV_LOCAL_FILE.write_text("\n".join(lines) + "\n")
    os.environ[key] = value  # take effect immediately, no restart needed
