from src.browser.session import BrowserSession
from src.agent.context import build_context_blob, infer_context
from src.agent.testgen import TestCaseGenerator
from src.agent.runner import TestRunner
from src.agent.observer import Observer
from src.safety.gate import SafetyGate
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import argparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main():
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://demoqa.com/automation-practice-form")
    args = parser.parse_args()

    llm = get_provider()

    async with BrowserSession(headless=False) as session:
        observer = Observer(session.page)         # attach BEFORE goto so we capture from load 0
        await session.goto(args.url)
        summary  = await session.summary()
        elements = await session.extract_elements()

        # generate the test plan (step 1 — already built)
        context = await infer_context(llm, build_context_blob(summary, elements))
        cases   = await TestCaseGenerator(llm).generate(elements, context)
        print(f"\nGenerated {len(cases)} test cases. Running…\n")

        # run them (step 3 — the new bit)
        gate = SafetyGate(llm)
        runner = TestRunner(session, gate, observer)
        results = await runner.run_suite(cases, args.url)

    # report
    passed = sum(r.passed for r in results)
    print(f"\n{'='*60}\n{passed}/{len(results)} cases passed\n{'='*60}\n")
    for r in results:
        mark = "✓" if r.passed else "✗"
        print(f"{mark} [{r.case.category:8}] {r.case.name}")
        print(f"           {r.detail}")
        if not r.passed:
            print(f"           ↪ review: expectation may be wrong, or the form may have a real issue")
        print()


if __name__ == "__main__":
    asyncio.run(main())
