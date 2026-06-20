"""Render a local HTML file to PDF using the project's bundled Chromium.

Usage: uv run python -m scripts.html_to_pdf <input.html> <output.pdf>
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def main(src: Path, dst: Path) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(src.resolve().as_uri())
        await page.pdf(
            path=str(dst),
            format="A4",
            print_background=True,
            margin={"top": "16mm", "bottom": "16mm", "left": "0mm", "right": "0mm"},
        )
        await browser.close()
    print(f"wrote {dst}")


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    asyncio.run(main(src, dst))