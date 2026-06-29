from src.agent.executor import Executor, find_submit
from src.agent.observer import Observer
from src.browser.session import BrowserSession
from src.llm import LLMProvider
from src.safety.gate import SafetyGate
from src.models.testcase import TestCase
from src.models.testresult import TestResult
import asyncio

_RELOAD_ATTEMPTS = 2          # a flaky/slow server gets a second chance
_RELOAD_TIMEOUT_MS = 60000    # LAN dev servers can be slow; default 30s is tight
# Hard ceiling per case: one stuck fill/submit can't freeze the whole run. Generous
# (a slow double-retry reload alone can take ~2 minutes); only a genuine hang trips it.
_CASE_BUDGET_S = 120

class TestRunner:
    def __init__(self, session: BrowserSession, gate: SafetyGate, observer: Observer) -> None:
        self.session = session
        self.observer = observer
        self.executor = Executor(session.page, gate)

    async def run_suite(self, cases: list[TestCase], seed_url: str) -> list[TestResult]:
        results = []
        for i, case in enumerate(cases, 1):
            print(f"[runner]   case {i}/{len(cases)}: {case.name}", flush=True)
            try:
                result = await asyncio.wait_for(
                    self.run_one(case, seed_url), timeout=_CASE_BUDGET_S
                )
            except asyncio.TimeoutError:
                print(f"[runner]   case {i} HUNG > {_CASE_BUDGET_S}s — recording error, moving on", flush=True)
                result = TestResult(
                    case=case, url=seed_url, observed="error",
                    passed=(case.expected == "unknown"),
                    detail=f"case exceeded {_CASE_BUDGET_S}s budget (hang guard tripped)",
                    findings=[],
                )
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
        # Removing any errors from previous case
        self.observer.collect_errors()

        # Reload for a clean form. If the server is unreachable/too slow even
        # after retries, record this case as an error and keep the suite alive.
        try:
            await self._reload(seed_url)
        except Exception as e:
            return TestResult(
                case=case,
                url=seed_url,
                observed="error",
                passed=(case.expected == "unknown"),
                detail=f"navigation failed after {_RELOAD_ATTEMPTS} attempts: {str(e)[:150]}",
                findings=[],
            )

        elements = await self.session.extract_elements()

        # Fill the case data and click submit
        print(f"[runner]     filling {len(case.field_values)} field(s) …", flush=True)
        await self.executor.fill_form(case.field_values, elements)
        submit = find_submit(elements)
        print("[runner]     submitting …", flush=True)
        click_result = await self.executor.click(submit) if submit else None
        print("[runner]     submitted, judging …", flush=True)

        case_findings = self.observer.collect_errors() + await self.observer.check_page()

        observed = self._judge(click_result, case_findings)
        passed = (observed == case.expected) or case.expected == "unknown"

        return TestResult(
            case=case,
            url=seed_url,
            observed=observed,
            passed=passed,
            detail=f"expected {case.expected!r}, observed {observed!r}",
            findings=case_findings
        )
    
    @staticmethod
    def _network_statuses(findings) -> list[int]:
        # The Observer records every 4xx/5xx response as a `network_error` Finding
        # whose description starts with the status code, e.g. "422 http://.../pay".
        # Pull those numbers back out so the judge can reason about them.
        # NOTE: this counts EVERY failed response in the case window, including
        # unrelated noise (a missing favicon, analytics 404s). Acceptable for now;
        # a later refinement would scope it to the actual submit request.
        statuses = []
        for f in findings:
            if f.category != "network_error":
                continue
            first = f.description.split()[0] if f.description else ""
            if first.isdigit():
                statuses.append(int(first))
        return statuses

    @staticmethod
    def _judge(click_result, findings) -> str:
        # The submit click never even fired — we have no answer to judge.
        if click_result is None or not click_result.ok:
            return "error"

        statuses = TestRunner._network_statuses(findings)

        # A 5xx means the server fell over while handling our submit. That isn't a
        # clean "your data was rejected" — it's the app breaking. Treat it as error.
        if any(s >= 500 for s in statuses):
            return "error"

        # Rejected if EITHER the client showed a validation message, OR the client
        # let the data through and the backend bounced it with a 4xx. The second
        # case is the one the old judge missed — a false "accepted".
        client_rejected = any(f.category == "validation" for f in findings)
        server_rejected = any(400 <= s < 500 for s in statuses)
        if client_rejected or server_rejected:
            return "rejected"

        # No validation message, no bad server response: the submit was accepted.
        return "accepted"
    
