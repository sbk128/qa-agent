from src.browser.session import BrowserSession
from src.agent.executor import Executor, find_submit
from src.agent.context import build_context_blob, infer_context
from src.data.generator import DataGenerator
from src.safety.gate import SafetyGate
from src.agent.observer import Observer
from src.llm import get_provider
from dotenv import load_dotenv
from pathlib import Path
import asyncio

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main():
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

    llm = get_provider()

    async with BrowserSession(headless=False) as session:   # headed so you can watch
        observer = Observer(session.page)
        await session.goto("http://localhost:5173/opd/waitlist")
        summary  = await session.summary()
        elements = await session.extract_elements()

        context = await infer_context(llm, build_context_blob(summary, elements))
        values  = await DataGenerator(llm).happy_path(elements, context)

        executor = Executor(session.page, SafetyGate(llm))
        fill_log = await executor.fill_form(values, elements)

        submit = find_submit(elements)
        click_log = await executor.click(submit) if submit else None

        findings = observer.collect_errors() + await observer.check_page()
        await asyncio.sleep(15)   # pause so you can see the result before it closes

    print("\n--- FILLS ---")
    for r in fill_log:
        print(r.model_dump())
    print("\n--- SUBMIT ---")
    print(click_log.model_dump() if click_log else "no submit button found")
    print("\n====FINDINGS====")
    for f in findings:
        print(f.model_dump())

if __name__ == "__main__":
    asyncio.run(main())
