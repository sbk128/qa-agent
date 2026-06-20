from src.browser.session import BrowserSession
from src.agent.agent_graph import build_agent_graph
from src.agent.observer import Observer
from src.llm import get_provider
from src.reporting.report import write_report
from dotenv import load_dotenv
from pathlib import Path
import asyncio, argparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

async def main():
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://demoqa.com/automation-practice-form")
    parser.add_argument("--locale", default=None)
    args = parser.parse_args()

    llm = get_provider()
    async with BrowserSession(headless=False) as session:
        observer = Observer(session.page)
        app = build_agent_graph(session, llm, observer)
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
            config={"recursion_limit": 50},
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