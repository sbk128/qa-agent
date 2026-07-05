from __future__ import annotations

import asyncio
import re
from pathlib import Path

from src.agent.executor import Executor, find_submit
from src.agent.observer import Observer
from src.browser.session import BrowserSession
from src.models.action import ActionResult
from src.models.testcase import TestCase
from src.models.testresult import TestResult
from src.safety.gate import SafetyGate

_RELOAD_ATTEMPTS = 2          # a flaky/slow server gets a second chance
_RELOAD_TIMEOUT_MS = 60000    # LAN dev servers can be slow; default 30s is tight
# Hard ceiling per case: one stuck fill/submit can't freeze the whole run. Generous
# (a slow double-retry reload alone can take ~2 minutes); only a genuine hang trips it.
_CASE_BUDGET_S = 120
# Circuit breaker: once the site stops responding (navigation fails/hangs) this many
# times in a row, stop hammering it — skip the rest of the page's cases instead of
# burning the full hang-budget on every one.
_CONSECUTIVE_FAIL_LIMIT = 2
# How long to let the page settle after a submit before we judge it: enough for a
# validation message to render or a submit XHR to come back, short enough not to stall.
_SETTLE_MS = 4000


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-")[:40] or "case"


class TestRunner:
    def __init__(
        self,
        session: BrowserSession,
        gate: SafetyGate,
        observer: Observer,
        *,
        evidence_dir: Path | None = None,
        capture_screenshots: bool = False,
    ) -> None:
        self.session = session
        self.observer = observer
        self.executor = Executor(session.page, gate)
        self._evidence_dir = Path(evidence_dir) if evidence_dir else None
        self._capture_screenshots = capture_screenshots and self._evidence_dir is not None
        self._shot_seq = 0

    async def run_suite(self, cases: list[TestCase], seed_url: str) -> list[TestResult]:
        results: list[TestResult] = []
        consec_fail = 0   # navigation failures/hangs in a row (circuit breaker)
        for i, case in enumerate(cases, 1):
            # Site looks dead — don't grind the remaining cases at ~2 min each.
            if consec_fail >= _CONSECUTIVE_FAIL_LIMIT:
                remaining = cases[i - 1:]
                print(
                    f"[runner]   site unresponsive {consec_fail}x in a row — "
                    f"skipping remaining {len(remaining)} case(s)",
                    flush=True,
                )
                for skipped in remaining:
                    results.append(self._skipped(
                        skipped, seed_url,
                        "site unresponsive (circuit breaker tripped)",
                    ))
                break

            print(f"[runner]   case {i}/{len(cases)}: {case.name}", flush=True)
            unreachable = False
            try:
                result = await asyncio.wait_for(
                    self.run_one(case, seed_url), timeout=_CASE_BUDGET_S
                )
            except TimeoutError:
                print(f"[runner]   case {i} HUNG > {_CASE_BUDGET_S}s — recording error, moving on", flush=True)
                result = await self._error(
                    case, seed_url, f"case exceeded {_CASE_BUDGET_S}s budget (hang guard tripped)"
                )
                unreachable = True
            else:
                # A skipped result whose reason is a navigation failure means the site
                # itself is unhealthy. A judged 'error' (submit didn't fire) does NOT —
                # the page loaded fine — so that resets the counter.
                unreachable = result.observed == "skipped" and "navigation failed" in (result.detail or "")

            consec_fail = consec_fail + 1 if unreachable else 0
            results.append(result)
        return results

    async def _reload(self, seed_url: str) -> None:
        # Retry the reload so one timed-out navigation can't abort the whole suite.
        last = None
        for attempt in range(_RELOAD_ATTEMPTS):
            try:
                await self.session.goto(seed_url, timeout=_RELOAD_TIMEOUT_MS)
                return
            except Exception as e:
                last = e
                print(f"[runner] reload {attempt + 1}/{_RELOAD_ATTEMPTS} failed: {str(e)[:120]}")
        raise last

    async def run_one(self, case: TestCase, seed_url: str) -> TestResult:
        self.observer.reset()   # drop anything buffered from the previous case

        # Reload for a clean form. If the server is unreachable/too slow even after
        # retries, this case never ran — record it as SKIPPED (not error, not pass).
        try:
            await self._reload(seed_url)
        except Exception as e:
            return self._skipped(
                case, seed_url,
                f"navigation failed after {_RELOAD_ATTEMPTS} attempts: {str(e)[:150]}",
            )

        elements = await self.session.extract_elements()

        # Fill the case data. Keep the per-field results so a failed fill can't be
        # mistaken for "the form accepted bad data" (the old code discarded these).
        print(f"[runner]     filling {len(case.field_values)} field(s) …", flush=True)
        fill_results = await self.executor.fill_form(case.field_values, elements)
        fill_failures = {r.selector: r.detail for r in fill_results if not r.ok}
        fallbacks = [r.selector for r in fill_results if r.fallback]

        # We could not enter the data we meant to — the verdict would be meaningless.
        if fill_failures:
            detail = "could not fill: " + "; ".join(f"{s} ({d})" for s, d in fill_failures.items())
            return await self._error(case, seed_url, detail, fill_failures=fill_failures)

        submit = find_submit(elements)
        print("[runner]     submitting …", flush=True)
        mark = self.observer.mark()          # only judge responses AFTER this point
        click_result = await self.executor.click(submit) if submit else None
        await self._settle()
        print("[runner]     submitted, judging …", flush=True)

        app_responses = self.observer.app_responses_since(mark)
        case_findings = self.observer.collect_errors() + await self.observer.check_page()

        observed = self._judge(click_result, case_findings, app_responses)
        passed = observed == case.expected   # no more auto-pass for expected="unknown"

        detail = f"expected {case.expected!r}, observed {observed!r}"
        if fallbacks:
            detail += f"  [note: substituted a valid value for {', '.join(fallbacks)}]"

        result = TestResult(
            case=case, url=seed_url, observed=observed, passed=passed,
            detail=detail, findings=case_findings,
        )
        result.screenshot_path = await self._maybe_capture(result)
        return result

    async def _settle(self) -> None:
        # Give the app a beat to render a validation message or return the submit XHR.
        try:
            await self.session.page.wait_for_load_state("networkidle", timeout=_SETTLE_MS)
        except Exception:
            # SPAs may never reach networkidle; a fixed short wait still lets the
            # client-side validation paint before we read the DOM.
            try:
                await self.session.page.wait_for_timeout(800)
            except Exception:
                pass

    # -- result constructors ------------------------------------------------ #
    async def _error(self, case, url, detail, fill_failures=None) -> TestResult:
        r = TestResult(
            case=case, url=url, observed="error", passed=False,
            detail=detail, findings=[], fill_failures=fill_failures or {},
        )
        r.screenshot_path = await self._maybe_capture(r)
        return r

    def _skipped(self, case, url, detail) -> TestResult:
        return TestResult(case=case, url=url, observed="skipped", passed=False, detail=detail)

    async def _maybe_capture(self, result: TestResult) -> str | None:
        # Screenshot cases a human should look at (review/error), so a finding can be
        # verified from the report without re-running. Passes/infos aren't captured.
        if not self._capture_screenshots or result.status in ("pass", "info", "skipped"):
            return None
        self._shot_seq += 1
        fname = f"{self._shot_seq:04d}-{_slug(result.case.name)}.png"
        try:
            await self.session.screenshot(self._evidence_dir / fname)
            return f"{self._evidence_dir.name}/{fname}"
        except Exception:
            return None

    # -- the judge ---------------------------------------------------------- #
    @staticmethod
    def _judge(click_result: ActionResult | None, findings, app_responses=()) -> str:
        """Decide accepted / rejected / error from what we observed.

        `app_responses` are ALREADY scoped to the app's own host (see Observer), so a
        third-party analytics 404 can no longer masquerade as the form being rejected.
        """
        # The submit click never even fired — we have no answer to judge.
        if click_result is None or not click_result.ok:
            return "error"

        statuses = [r["status"] for r in app_responses]

        # A 5xx means the server fell over while handling our submit — the app broke,
        # which is an error, not a clean "your data was rejected".
        if any(s >= 500 for s in statuses):
            return "error"

        # Rejected if the client showed a validation message, OR the backend bounced
        # the data with a 4xx.
        client_rejected = any(f.category == "validation" for f in findings)
        server_rejected = any(400 <= s < 500 for s in statuses)
        if client_rejected or server_rejected:
            return "rejected"

        # No validation message, no bad server response: the submit was accepted.
        return "accepted"
