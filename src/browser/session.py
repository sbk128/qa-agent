"""Thin async wrapper around a single Playwright page.

Opens a URL, grabs a small text summary for the LLM, takes screenshots/traces,
and extracts the interactive elements (via PageSnapshotter).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from src.browser.snapshotter import PageSnapshotter
from src.models.element import Element


@dataclass
class PageSummary:  # Phase 0: Page description to go into LLM prompt.
    url: str
    title: str
    headings: list[str] = field(default_factory=list)
    text_preview: str = ""
    

    def to_prompt(self) -> str: # This is the output from the browser that goes into LLM prompt. It is not a full snapshot, just a few key fields.
        lines = [f"URL: {self.url}", f"Title: {self.title or '(none)'}"]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings[:5]))
        if self.text_preview:
            lines.append(f"Text: {self.text_preview}")
        return "\n".join(lines)


class BrowserSession: # Opens a new browser session.
    def __init__(self, headless: bool = True, storage_state: str | Path | None = None) -> None:
        self._headless = headless
        # Path to a saved Playwright storage_state (cookies + localStorage, incl. the
        # SSO JWT). When the file exists, the context starts already authenticated.
        self._storage_state = storage_state
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> Self:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            # The flag is --window-size (the old "--window-side" was a typo, so
            # Chromium silently ignored it). Pin the window to the top-left so it
            # doesn't get centered and spill off both edges of the screen.
            args=["--window-size=1280,860", "--window-position=0,0"])

        # Viewport = the page area. A 13.6" MacBook Air is ~1470x956 points; keep
        # the page well inside that so the whole window (menu bar + browser chrome
        # + page) is visible at once instead of running off-screen.
        context_kwargs = {"viewport": {"width": 1280, "height": 740}}
        if self._storage_state and Path(self._storage_state).exists():
            context_kwargs["storage_state"] = str(self._storage_state)
        self._context = await self._browser.new_context(**context_kwargs)

        self._page = await self._context.new_page()
        return self

    async def save_storage_state(self, path: str | Path) -> Path:
        """Persist cookies + localStorage (the authenticated session) to disk."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(out))
        return out

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession not entered")
        return self._page

    async def goto(self, url: str, *, wait_until: str = "domcontentloaded",
                   timeout: float | None = None):
        response = await self.page.goto(url, wait_until=wait_until, timeout=timeout)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # Some pages never go idle
        return response

    async def start_tracing(self) -> None:
        """Begin a Playwright trace (screenshots + snapshots + sources) for the run."""
        if self._context is not None:
            await self._context.tracing.start(screenshots=True, snapshots=True, sources=True)

    async def stop_tracing(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self._context is not None:
            await self._context.tracing.stop(path=str(out))
        return out

    async def screenshot(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(out), full_page=True)
        return out

    async def summary(self, text_chars: int = 500) -> PageSummary:
        page = self.page
        title = await page.title()

        try:
            headings = await page.eval_on_selector_all(
                "h1, h2",
                "els => els.slice(0, 10)"
                ".map(e => (e.innerText || '').trim())"
                ".filter(Boolean)",
            )
        except Exception:
            headings = []

        try:
            text = await page.inner_text("body", timeout=5000)
        except Exception:
            text = ""
        text = " ".join(text.split())[:text_chars]

        return PageSummary(
            url=page.url,
            title=title,
            headings=headings,
            text_preview=text,
        )
     
    async def extract_elements(self) -> list[Element]:
        return await PageSnapshotter(self.page).extract_elements()
