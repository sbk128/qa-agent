"""Test forms that only exist after clicking a launcher (a modal dialog).

Many apps hide a form behind an "Add / New / Create / Edit" button — clicking it
opens a MUI dialog with the real form. The normal snapshot can't see that form, so
the test engine skips the page. ModalTester closes that gap:

    discover launchers (across tabs) -> for each:
        open the modal -> snapshot scoped to the dialog -> generate a suite ->
        run each case (reload, re-open, fill inside the dialog, submit, observe) ->
        close the dialog.

It reuses the existing Executor / TestCaseGenerator / Observer / find_submit, and the
same judge as TestRunner, so a modal form is tested exactly like a normal one.
"""
from __future__ import annotations

from src.agent.executor import Executor, find_submit
from src.agent.observer import Observer
from src.agent.runner import TestRunner
from src.agent.testgen import TestCaseGenerator
from src.browser.session import BrowserSession
from src.browser.snapshotter import PageSnapshotter
from src.models.context import InferredContext
from src.models.testcase import TestCase
from src.models.testresult import TestResult
from src.safety.gate import SafetyGate

_LAUNCH_VERBS = ("add", "new", "create", "edit")
_DIALOG_SEL = '[role="dialog"], .MuiDialog-root, .MuiModal-root'
_CLOSE_WORDS = ("cancel", "close", "discard")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class ModalTester:
    def __init__(self, session: BrowserSession, gate: SafetyGate,
                 observer: Observer, testgen: TestCaseGenerator) -> None:
        self.session = session
        self.observer = observer
        self.testgen = testgen
        self.executor = Executor(session.page, gate)

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
        # STARTS WITH a verb — so "Add Payment" matches but the "Patient Payments" tab doesn't.
        return [l for l in labels if l.lower().startswith(_LAUNCH_VERBS)]

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
        for word in _CLOSE_WORDS:
            try:
                await self.page.get_by_role("button", name=word, exact=False).first.click(timeout=1200)
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
        return [await self._run_case(seed_url, tab, label, case, url) for case in cases]

    async def _run_case(self, seed_url: str, tab: str | None, label: str,
                        case: TestCase, url: str) -> TestResult:
        self.observer.collect_errors()  # drop anything buffered from the previous case

        # Each case needs a fresh modal: reload the page, re-open the dialog.
        try:
            await self.session.goto(seed_url)
            if tab:
                await self._activate_tab(tab)
            dlg = await self._open_modal(label)
        except Exception as e:
            return self._error(case, url, f"reopen failed: {str(e)[:120]}")
        if dlg is None:
            return self._error(case, url, "modal did not reopen")

        elements = await PageSnapshotter(self.page).extract_elements(root=dlg)
        await self.executor.fill_form(case.field_values, elements)
        submit = find_submit(elements)
        click_result = await self.executor.click(submit) if submit else None

        case_findings = self.observer.collect_errors() + await self.observer.check_page()
        observed = TestRunner._judge(click_result, case_findings)
        passed = (observed == case.expected) or case.expected == "unknown"
        await self._close_modal()

        return TestResult(
            case=case, url=url, observed=observed, passed=passed,
            detail=f"expected {case.expected!r}, observed {observed!r}",
            findings=case_findings,
        )

    @staticmethod
    def _error(case: TestCase, url: str, detail: str) -> TestResult:
        return TestResult(
            case=case, url=url, observed="error",
            passed=(case.expected == "unknown"), detail=detail, findings=[],
        )
