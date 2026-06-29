"""Isolate where a run hangs by timing JUST the first-page snapshot.

The full run goes silent after startup, so we can't see where it sticks. This
loads ONE page (with auth) and times each stage. Read the output:
  - stops after [1]  -> navigation (goto) is the hang
  - stops after [2]  -> extract_elements (reading the page) is the hang
  - reaches [3]      -> the snapshot is FINE; the hang is later (LLM / test engine)

Run with the SAME start URL you put in the app, e.g.:
  uv run python scripts/time_snapshot.py "http://192.168.0.191:8000/accounting"
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.session import BrowserSession

AUTH = "auth.json"


async def main(url: str) -> None:
    auth = AUTH if Path(AUTH).exists() else None
    async with BrowserSession(headless=True, storage_state=auth) as session:
        t0 = time.perf_counter()
        print(f"[1] navigating to {url} ...", flush=True)
        await session.goto(url)
        print(f"[2] page loaded in {time.perf_counter() - t0:.1f}s — now snapshotting ...", flush=True)

        t1 = time.perf_counter()
        elements = await session.extract_elements()
        print(f"[3] extract_elements done in {time.perf_counter() - t1:.1f}s "
              f"— found {len(elements)} elements", flush=True)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.0.191:8000/accounting"
    asyncio.run(main(target))
