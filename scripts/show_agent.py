from src.browser.session import BrowserSession
from src.agent.agent_graph import build_agent_graph
from src.agent.observer import Observer
from src.llm import get_provider
from src.reporting.report import write_report
from dotenv import load_dotenv
from pathlib import Path
import asyncio, argparse, json

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _has_session(path: Path) -> bool:
    # A valid saved session has at least a cookie or a localStorage origin.
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    return bool(data.get("cookies") or data.get("origins"))


async def main():
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://demoqa.com/automation-practice-form")
    parser.add_argument("--locale", default=None)
    parser.add_argument("--auth", default="auth.json",
                        help="Saved session file from login.py (cookies + localStorage incl. JWT).")
    parser.add_argument("--allow-all", action="store_true",
                        help="Sandbox: disable the destructive safety gate (test dev targets where "
                             "financial submits like 'Submit Transaction' should be exercised).")
    args = parser.parse_args()

    auth_path = _PROJECT_ROOT / args.auth
    # Reuse a captured session if it's real; otherwise run unauthenticated.
    if _has_session(auth_path):
        storage_state = auth_path
        print(f"Using saved session: {auth_path}")
    else:
        storage_state = None
        if auth_path.exists():
            print(f"⚠️  {auth_path} has no session data — run scripts/login.py first if this "
                  f"page needs auth. Continuing unauthenticated.")

    llm = get_provider()
    async with BrowserSession(headless=False, storage_state=storage_state) as session:

        observer = Observer(session.page)
        if args.allow_all:
            print("⚠️  --allow-all: safety gate disabled (sandbox mode).")
        app = build_agent_graph(session, llm, observer, allow_all=args.allow_all)
        final = await app.ainvoke(
            {
                "seed_url": args.url,
                "visited_urls": [],
                "action_history": [],
                "findings": [],
                "frontier": [],
                "iteration": 0,
                "test_results": [],
                "locale": args.locale
            },
            config={"recursion_limit": 150},  # ~6 graph nodes per crawl lap × MAX_ITERATIONS + margin
        )
        out = write_report(final)

    test_results = final.get("test_results", [])
    test_passed = sum(r.passed for r in test_results)

    print(f"\nLaps: {final.get('iteration')}   Visited: {len(final.get('visited_urls', []))}")
    print(f"Tests: {test_passed}/{len(test_results)} cases passed")
    print(f"Report written to: {out}/report.md")

    print("\n ---- ACTION HISTORY ----")
    for a in final.get("action_history", []):
        print(a.model_dump())
    print("\n ----FINDINGS----")
    for f in final.get("findings", []):
        print(f.model_dump())

if __name__ == "__main__":
    asyncio.run(main())