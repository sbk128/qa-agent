"""Capture an authenticated browser session for later crawling.

Opens a headed browser at the login page, waits for YOU to log in by hand,
then saves cookies + localStorage (incl. the JWT) to a file. The crawler
(show_agent.py) reuses that file so it starts already authenticated.

The test agent is deliberately NOT involved here, so nothing types into or
submits the login form — the page is fully yours.

    uv run python scripts/login.py --url http://192.168.0.191:8000/login
"""
import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from src.browser.session import BrowserSession

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _wait_for_enter() -> None:
    # Fallback completion signal. If stdin isn't interactive, never resolve via
    # Enter — rely on the URL-change detection instead.
    try:
        await asyncio.get_event_loop().run_in_executor(None, input, "")
    except EOFError:
        await asyncio.Event().wait()


async def main():
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Login page URL")
    parser.add_argument("--auth", default="auth.json", help="Where to save the session")
    args = parser.parse_args()

    auth_path = _PROJECT_ROOT / args.auth

    async with BrowserSession(headless=False) as session:
        page = session.page
        await session.goto(args.url)

        print("\n" + "=" * 64)
        print("Log in in the browser window with your real credentials.")
        print("I'll capture the session automatically once you leave the login")
        print("page — or just press Enter here after you're logged in.")
        print("=" * 64 + "\n")

        # Whichever happens first wins: you navigate off /login, or you hit Enter.
        left_login = asyncio.create_task(
            page.wait_for_url(lambda u: "login" not in u.lower(), timeout=0)
        )
        pressed_enter = asyncio.create_task(_wait_for_enter())
        _, pending = await asyncio.wait(
            {left_login, pressed_enter}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

        # Let the app settle so the token is actually persisted before we read it.
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        saved = await session.save_storage_state(auth_path)

    data = json.loads(Path(saved).read_text())
    n_cookies = len(data.get("cookies", []))
    n_origins = len(data.get("origins", []))
    print(f"\nSaved session to {saved}")
    print(f"  cookies: {n_cookies} | localStorage origins: {n_origins}")
    if n_cookies == 0 and n_origins == 0:
        print("  ⚠️  This session looks EMPTY — you probably weren't logged in.")
        print("      Re-run, finish logging in, and make sure the app loads first.")
    else:
        print("  ✓ Looks good. Now run show_agent.py against a page behind auth.")


if __name__ == "__main__":
    asyncio.run(main())