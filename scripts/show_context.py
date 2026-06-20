from src.browser.session import BrowserSession
from src.agent.context import build_context_blob, infer_context
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import argparse

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

    for url in urls:
        print(f"\n\n=== {url} ===")
        async with BrowserSession() as session:
            await session.goto(url)
            summary = await session.summary()
            elements = await session.extract_elements()
            blob = build_context_blob(summary, elements)
            context = await infer_context(llm, blob)
        print(context.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
