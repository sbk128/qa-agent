from src.browser.session import BrowserSession
from src.agent.testgen import TestCaseGenerator
from src.agent.context import build_context_blob, infer_context
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import argparse

# scripts/show_testcases.py -> scripts/ -> qa-agent/  (the project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main():
    # Anchored to the project root so it loads from any cwd.
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://demoqa.com/automation-practice-form",
        help="URL of the form/page to generate test cases for",
    )
    args = parser.parse_args()

    llm = get_provider()

    async with BrowserSession() as session:
        await session.goto(args.url)
        summary = await session.summary()
        elements = await session.extract_elements()

    context = await infer_context(llm, build_context_blob(summary, elements))
    cases = await TestCaseGenerator(llm).generate(elements, context)

    print(f"\n=== {args.url} ===")
    print(f"Generated {len(cases)} test cases:\n")
    for c in cases:
        print(f"[{c.category}] {c.name}  → expect: {c.expected}")
        print(f"    {c.description}")
        print(f"    data: {c.field_values}")
        print(f"    why:  {c.rationale}\n")


if __name__ == "__main__":
    asyncio.run(main())
