"""Test forms that only exist after clicking a launcher (a modal dialog).

Many apps hide a form behind an "Add / New / Create / Edit" button — clicking it
opens a MUI dialog with the real form. The normal snapshot can't see that form, so
the test engine skips the page. ModalTester closes that gap:

    discover launchers (across tabs) -> for each:
        open the modal -> snapshot scoped to the dialog -> generate a suite ->
        run each case (reload, re-open, fill inside the dialog, submit, observe) ->
        close the dialog.

It reuses the Executor / TestCaseGenerator / Observer / find_submit and the same
judge, hang guard, and circuit breaker as TestRunner, so a modal form is tested and
protected exactly like a normal one.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from src.agent.executor import Executor, find_submit
from src.agent.observer import Observer
from src.agent.runner import (
    _CASE_BUDGET_S,
    _CONSECUTIVE_FAIL_LIMIT,
    _SETTLE_MS,
    TestRunner,
    _slug,
)
from src.agent.testgen import TestCaseGenerator
from src.browser.session import BrowserSession
from src.browser.snapshotter import PageSnapshotter
from src.models.context import InferredContext
from src.models.element import Element
from src.models.testcase import TestCase
from src.models.testresult import TestResult
from src.safety.gate import SafetyGate

_LAUNCH_VERBS = ("add", "new", "create", "edit")
# A label that STARTS WITH a launch verb as a whole word: "Add Payment" and "New"
# match, but "Address Book" (starts with "add" mid-word) does not.
_LAUNCH_RE = re.compile(rf"^(?:{'|'.join(_LAUNCH_VERBS)})\b", re.IGNORECASE)
_DIALOG_SEL = '[role="dialog"], .MuiDialog-root, .MuiModal-root'
_CLOSE_WORDS = ("cancel", "close", "discard")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class ModalTester:
    def __init__(self, session: BrowserSession, gate: SafetyGate,
                 observer: Observer, testgen: TestCaseGenerator,
                 *, evidence_dir: Path | None = None,
                 capture_screenshots: bool = False) -> None:
        self.session = session
        self.gate = gate
        self.observer = observer
        self.testgen = testgen
        self.executor = Executor(session.page, gate)
        self._evidence_dir = Path(evidence_dir) if evidence_dir else None
        self._capture_screenshots = capture_screenshots and self._evidence_dir is not None
        self._shot_seq = 0

    @property
    def page(self):
        return self.session.page

    async def run(self, seed_url: str, context: InferredContext | None) -> list[TestResult]:
        """Find every modal launcher on `seed_url` and test the form each opens."""
        results: list[TestResult] = []
        for tab, label in await self._discover_launchers(seed_url):
            results.extend(await self._test_launcher(seed_url, tab, label, context))
        return results

    # -- discovery ---------------------------------------------------------- #
    async def _discover_launchers(self, seed_url: str) -> list[tuple[str | None, str]]:
        # Launchers can hide behind tabs, so walk the tabs and collect verb-prefixed
        # buttons revealed under each. dedup by label (first tab that shows it wins).
        await self.session.goto(seed_url)
        tabs = await self.page.eval_on_selector_all(
            '[role="tab"]', 'els => els.map(t => (t.innerText || "").trim()).filter(Boolean)'
        )
        found: dict[str, str | None] = {}
        if tabs:
            for tab in tabs:
                if not await self._activate_tab(tab):
                    continue
                for lbl in await self._visible_launchers():
                    found.setdefault(lbl, tab)
        else:
            for lbl in await self._visible_launchers():
                found.setdefault(lbl, None)
        return [(tab, label) for label, tab in found.items()]

    async def _visible_launchers(self) -> list[str]:
        labels = await self.page.eval_on_selector_all(
            "button",
            'els => els.filter(b => b.offsetParent !== null)'
            '.map(b => (b.innerText || "").trim()).filter(Boolean)',
        )
        # Whole-word verb prefix — "Add Payment" matches, "Address Book" doesn't.
        return [lbl for lbl in labels if _LAUNCH_RE.match(lbl)]

    # -- modal open/close --------------------------------------------------- #
    async def _activate_tab(self, tab_label: str) -> bool:
        try:
            await self.page.get_by_role("tab", name=tab_label, exact=True).first.click(timeout=3000)
            await self.page.wait_for_timeout(400)
            return True
        except Exception:
            return False

    async def _open_modal(self, label: str):
        try:
            await self.page.locator(f'button:has-text("{_esc(label)}")').first.click(timeout=6000)
        except Exception:
            return None
        try:
            return await self.page.wait_for_selector(_DIALOG_SEL, state="visible", timeout=4000)
        except Exception:
            return None  # not a modal launcher (e.g. an inline-row "Add")

    async def _close_modal(self) -> None:
        # Scope the close button to the dialog so we never click a page-level button
        # like "Close account" that happens to contain a close word.
        dialog = self.page.locator(_DIALOG_SEL).first
        for word in _CLOSE_WORDS:
            try:
                await dialog.get_by_role("button", name=word, exact=False).first.click(timeout=1200)
                break
            except Exception:
                continue
        else:
            await self.page.keyboard.press("Escape")
        try:
            await self.page.wait_for_selector(_DIALOG_SEL, state="hidden", timeout=2500)
        except Exception:
            pass

    # -- per-launcher testing ---------------------------------------------- #
    async def _test_launcher(self, seed_url: str, tab: str | None, label: str,
                             context: InferredContext | None) -> list[TestResult]:
        # Don't open a launcher the safety gate would block (defense in depth — the
        # verb filter already excludes delete/pay, but a config block could add more).
        verdict = await self.gate.evaluate(
            Element(tag="button", name=label, selector=f'button:has-text("{_esc(label)}")')
        )
        if self.gate.should_block(verdict):
            print(f"[modal] skipping launcher {label!r}: {verdict.reason}")
            return []

        # Open once to read the modal's fields and generate the suite.
        await self.session.goto(seed_url)
        if tab:
            await self._activate_tab(tab)
        dlg = await self._open_modal(label)
        if dlg is None:
            return []  # launcher didn't open a dialog — nothing to test here
        elements = await PageSnapshotter(self.page).extract_elements(root=dlg)
        await self._close_modal()

        try:
            cases = await self.testgen.generate(elements, context)
        except Exception as e:
            print(f"[modal] test-case generation failed for {label!r}: {str(e)[:120]}")
            return []
        if not cases:
            return []

        # Tag results with the launcher so the report groups one section per modal.
        url = f"{self.page.url}#{label}"
        print(f"[modal] testing {label!r} ({len(cases)} cases)")
        return await self._run_cases(seed_url, tab, label, cases, url)

    async def _run_cases(self, seed_url, tab, label, cases, url) -> list[TestResult]:
        # Same hang guard + circuit breaker as TestRunner.run_suite.
        results: list[TestResult] = []
        consec_fail = 0
        for i, case in enumerate(cases, 1):
            if consec_fail >= _CONSECUTIVE_FAIL_LIMIT:
                for skipped in cases[i - 1:]:
                    results.append(TestResult(
                        case=skipped, url=url, observed="skipped", passed=False,
                        detail="site unresponsive (circuit breaker tripped)",
                    ))
                break
            unreachable = False
            try:
                result = await asyncio.wait_for(
                    self._run_case(seed_url, tab, label, case, url), timeout=_CASE_BUDGET_S
                )
            except TimeoutError:
                result = TestResult(
                    case=case, url=url, observed="error", passed=False,
                    detail=f"case exceeded {_CASE_BUDGET_S}s budget (hang guard tripped)",
                )
                unreachable = True
            else:
                unreachable = result.observed == "skipped" and "did not reopen" in (result.detail or "")
            consec_fail = consec_fail + 1 if unreachable else 0
            results.append(result)
        return results

    async def _run_case(self, seed_url: str, tab: str | None, label: str,
                        case: TestCase, url: str) -> TestResult:
        self.observer.reset()   # drop anything buffered from the previous case

        # Each case needs a fresh modal: reload the page, re-open the dialog.
        try:
            await self.session.goto(seed_url)
            if tab:
                await self._activate_tab(tab)
            dlg = await self._open_modal(label)
        except Exception as e:
            return self._skipped(case, url, f"modal did not reopen: {str(e)[:120]}")
        if dlg is None:
            return self._skipped(case, url, "modal did not reopen")

        elements = await PageSnapshotter(self.page).extract_elements(root=dlg)

        fill_results = await self.executor.fill_form(case.field_values, elements)
        fill_failures = {r.selector: r.detail for r in fill_results if not r.ok}
        if fill_failures:
            await self._close_modal()
            detail = "could not fill: " + "; ".join(f"{s} ({d})" for s, d in fill_failures.items())
            return await self._finish(TestResult(
                case=case, url=url, observed="error", passed=False,
                detail=detail, fill_failures=fill_failures,
            ))

        submit = find_submit(elements)
        mark = self.observer.mark()
        click_result = await self.executor.click(submit) if submit else None
        await self._settle()

        app_responses = self.observer.app_responses_since(mark)
        case_findings = self.observer.collect_errors() + await self.observer.check_page()
        observed = TestRunner._judge(click_result, case_findings, app_responses)
        passed = observed == case.expected
        await self._close_modal()

        return await self._finish(TestResult(
            case=case, url=url, observed=observed, passed=passed,
            detail=f"expected {case.expected!r}, observed {observed!r}",
            findings=case_findings,
        ))

    async def _settle(self) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=_SETTLE_MS)
        except Exception:
            try:
                await self.page.wait_for_timeout(800)
            except Exception:
                pass

    def _skipped(self, case: TestCase, url: str, detail: str) -> TestResult:
        return TestResult(case=case, url=url, observed="skipped", passed=False, detail=detail)

    async def _finish(self, result: TestResult) -> TestResult:
        result.screenshot_path = await self._maybe_capture(result)
        return result

    async def _maybe_capture(self, result: TestResult) -> str | None:
        if not self._capture_screenshots or result.status in ("pass", "info", "skipped"):
            return None
        self._shot_seq += 1
        fname = f"modal-{self._shot_seq:04d}-{_slug(result.case.name)}.png"
        try:
            await self.session.screenshot(self._evidence_dir / fname)
            return f"{self._evidence_dir.name}/{fname}"
        except Exception:
            return None
