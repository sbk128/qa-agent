from src.browser.session import BrowserSession
import asyncio
import argparse

async def main():
    url = "https://the-internet.herokuapp.com/login"
    urls = [
            # "https://the-internet.herokuapp.com/login",
            # "https://www.saucedemo.com",
            # "https://demoqa.com/text-box",
            # "https://demoqa.com/select-menu",
            "http://localhost:5173/opd/showappointments?timeFilter=today"
            ]

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="URL", default=url)
    args = parser.parse_args()
    url = args.url
    
    for url in urls:
        print(f"\n\n=== {url} ===")

        async with BrowserSession() as session:
            await session.goto(url)
            # summary = await session.summary()
            # print(summary.to_prompt())
            elements = await session.extract_elements()
            for el in elements:
                print(el)


if __name__ == "__main__":
    asyncio.run(main())
