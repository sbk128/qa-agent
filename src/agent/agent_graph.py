from urllib.parse import urlparse
from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.context import build_context_blob, infer_context
from src.agent.executor import Executor, find_submit
from src.data.generator import DataGenerator
from src.safety.gate import SafetyGate
from src.agent.testgen import TestCaseGenerator
from src.agent.runner import TestRunner
from src.agent.modal_tester import ModalTester

MAX_ITERATIONS = 12
DEFAULT_COUNTRY = "IN"

def _log(msg: str) -> None:
    # Progress breadcrumbs to the console / GUI log. A "→ step" with no matching
    # "ok" line right after it is exactly where a run is hung.
    print(f"[graph] {msg}", flush=True)

def build_agent_graph(session, llm, observer, allow_all=False):
    gate = SafetyGate(llm, allow_all=allow_all)
    testgen = TestCaseGenerator(llm)
    runner = TestRunner(session, gate, observer)
    modal_tester = ModalTester(session, gate, observer, testgen)

    async def snapshot_node(state: AgentState) -> AgentState:
        target = state.get("next_url") or state["seed_url"]
        _log(f"→ snapshot: {target}")
        await session.goto(target)
        page = session.page
        elements = await session.extract_elements()
        summary = await session.summary()
        
        seed_host = urlparse(state["seed_url"]).netloc
        raw = await page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
        links = list(dict.fromkeys(u for u in raw if urlparse(u).netloc == seed_host))
        _log(f"  snapshot ok: {len(elements)} elements, {len(links)} links")
        return {
            "current_url": page.url,
            "summary": summary,
            "elements": elements,
            "links": links,
            "visited_urls": [target],
            "iteration": state.get("iteration", 0) + 1
        }
    
    async def context_node(state:AgentState) -> AgentState:
        _log("→ infer_context (LLM call) …")
        blob = build_context_blob(state["summary"], state["elements"])
        context = await infer_context(llm, blob)
        _log("  infer_context ok")

        override = state.get('locale')
        if override:
            context.country_hint = override
        elif not context.country_hint:
            context.country_hint = DEFAULT_COUNTRY
        return {"context": context}
    
    async def plan_node(state: AgentState) -> AgentState:
        # No submittable form on this page (e.g. a read-only list/table) — there's
        # nothing for the test engine to fill + submit, so skip it. Avoids a bogus
        # all-"error" suite and saves an LLM call.
        if find_submit(state["elements"]) is None:
            _log("→ plan: no submittable form, skipping")
            return {"test_cases": []}
        _log("→ plan: generating test cases (LLM call) …")
        # The test-case LLM call can fail — transient Groq errors, or invalid/oversized
        # JSON on big forms (many fields + long positional selectors). Don't let that
        # abort the whole crawl: skip this page's suite and keep going.
        try:
            cases = await testgen.generate(state["elements"], state["context"])
        except Exception as e:
            print(f"[plan] test-case generation failed, skipping page: {str(e)[:150]}")
            cases = []
        _log(f"  plan ok: {len(cases)} cases")
        return {"test_cases": cases}
    
    async def execute_node(state: AgentState) -> AgentState:
        url = state["current_url"]
        _log(f"→ execute: {len(state.get('test_cases', []))} page case(s) + modal scan …")
        results = []
        # 1. the page's own form (if it had one)
        cases = state.get("test_cases", [])
        if cases:
            results += await runner.run_suite(cases, url)
        # 2. any forms hidden behind launcher buttons (modals) — runs even when the
        #    page body has no form of its own (e.g. the IPD Billing dashboard).
        results += await modal_tester.run(url, state.get("context"))
        _log(f"  execute ok: {len(results)} result(s)")
        return {"test_results": results} if results else {}

    
    async def observe_node(state: AgentState) -> AgentState:
        _log("→ observe")
        return {"findings": observer.collect_errors() + await observer.check_page()}
    
    async def decide_node(state):
        _log("→ decide: choosing next page")
        visited = set(state.get("visited_urls", []))
        frontier = list(state.get("frontier", []))
        
        # Addign newly discovered links to the frontier
        for url in state.get("links", []):
            if url not in visited and url not in frontier:
                frontier.append(url)
        
        # Cross off anything we've since visited
        frontier = [u for u in frontier if u not in visited]

        # Pick the next target
        # Breadth-first --- Take from the front
        if frontier and state.get("iteration", 0) < MAX_ITERATIONS:
            next_url = frontier.pop(0)
            return {"next_url": next_url, "frontier": frontier}
        
        # Nothing left or capped
        return {"next_url": None, "frontier": frontier}

    
    def route(state):
        return "snapshot" if state.get("next_url") else END

    # Graph
    g = StateGraph(AgentState)
    g.add_node("snapshot", snapshot_node)
    g.add_node("infer_context", context_node)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("observe", observe_node)
    g.add_node("decide", decide_node)


    g.set_entry_point("snapshot")
    g.add_edge("snapshot", "infer_context")
    g.add_edge("infer_context", "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "observe")
    g.add_edge("observe", "decide")
    g.add_conditional_edges("decide", route)
    g.add_edge("observe", END)

    return g.compile()
