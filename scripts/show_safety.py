from src.models.element import Element
from src.safety.gate import SafetyGate
from src.browser.session import BrowserSession
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import argparse

# scripts/show_safety.py -> scripts/ -> qa-agent/  (the project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main():
    # Anchored to the project root so it loads from any cwd.
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="run the gate over a live page's elements")
    args = parser.parse_args()

    gate = SafetyGate(get_provider())

    if args.url:
        # Live mode: extract a real page's elements and gate each one.
        async with BrowserSession() as session:
            await session.goto(args.url)
            elements = await session.extract_elements()
        for el in elements:
            if not el.visible:
                continue
            verdict = await gate.evaluate(el)
            flag = "  ⚠️" if verdict.risk != "safe" else ""
            print(f"{(el.name or '')[:24]:24} → {verdict.risk:12}{flag}")
    else:
        # Isolation mode: hand-made elements to exercise each layer of the gate.
        fakes = [
            Element(tag="button", name="Delete account", selector="x"),  # L1 destructive
            Element(tag="button", name="Pay now", selector="x"),         # L1 destructive
            Element(tag="a", name="Logout", selector="x"),               # L1 destructive
            Element(tag="button", name="Submit", selector="x"),          # L2 -> LLM
            Element(tag="button", name="Save", selector="x"),            # L2 -> LLM
            Element(tag="input", name="Username", selector="x"),         # default safe
            Element(tag="a", name="Home", selector="x"),                 # default safe
        ]
        for el in fakes:
            verdict = await gate.evaluate(el)
            print(f"{el.name:16} → {verdict.risk:12} | {verdict.reason}")


if __name__ == "__main__":
    asyncio.run(main())
