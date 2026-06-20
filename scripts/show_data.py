from src.browser.session import BrowserSession
from src.agent.context import build_context_blob, infer_context
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio
from src.data.generator import DataGenerator
import argparse
from src.data.generator import fillable

# scripts/show_context.py -> scripts/ -> qa-agent/  (the project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main():
    # Anchor the .env path to the project root so it loads no matter
    # which directory you launch the script from. .env.local wins over .env.
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

    default_url = "https://demoqa.com/automation-practice-form"

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="URL", default=default_url)
    args = parser.parse_args()

    # Add more URLs here to compare context inference across sites.
    urls = [args.url]

    llm = get_provider()
    gen = DataGenerator(llm)

    for url in urls:
        print(f"\n\n=== {url} ===")
        async with BrowserSession() as session:
            await session.goto(url)
            summary = await session.summary()
            elements = await session.extract_elements()

        context = await infer_context(
            llm,
            build_context_blob(summary, elements)
        )

        print("\n\n--- HAPPY PATH ---")
        values = await gen.happy_path(elements, context)
        for selector, value in values.items():
            print(f"{value!r:30} -> {selector}")
        
        print("\n\n--- EDGE CASES ---")
        fields = fillable(elements)
        if fields:
            for v in gen.edge_cases(fields[0]):
                print(repr(v))


if __name__ == "__main__":
    asyncio.run(main())
