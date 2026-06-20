from src.agent.executor import Executor, find_submit
from src.agent.observer import Observer
from src.browser.session import BrowserSession
from src.llm import LLMProvider
from src.safety.gate import SafetyGate
from src.models.testcase import TestCase
from src.models.testresult import TestResult

class TestRunner:
    def __init__(self, session: BrowserSession, gate: SafetyGate, observer: Observer) -> None:
        self.session = session
        self.observer = observer
        self.executor = Executor(session.page, gate)

    async def run_suite(self, cases: list[TestCase], seed_url: str) -> list[TestResult]:
        results = []
        for case in cases:
            results.append(await self.run_one(case, seed_url))
        return results
    
    async def run_one(self, case: TestCase, seed_url: str) -> TestResult:
        # Removing any errors from previous case
        self.observer.collect_errors()
        
        # Reload for a clean form
        await self.session.goto(seed_url)
        elements = await self.session.extract_elements()

        # Fill the case data and click submit
        await self.executor.fill_form(case.field_values, elements)
        submit = find_submit(elements)
        click_result = await self.executor.click(submit) if submit else None

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
    def _judge(click_result, findings) -> str:
        if click_result is None or not click_result.ok:
            return "error"
        if any(f.category == "validation" for f in findings):
            return "rejected"
        return "accepted"
    
