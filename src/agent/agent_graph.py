from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse

from langgraph.graph import END, StateGraph

from src.agent.context import build_context_blob, infer_context
from src.agent.executor import find_submit
from src.agent.modal_tester import ModalTester
from src.agent.runner import TestRunner
from src.agent.state import AgentState
from src.agent.testgen import TestCaseGenerator
from src.config import AppConfig
from src.safety.gate import SafetyGate, url_is_blocked

DEFAULT_COUNTRY = "IN"


def _log(msg: str) -> None:
    # Progress breadcrumbs to the console / GUI log. A "→ step" with no matching
    # "ok" line right after it is exactly where a run is hung.
    print(f"[graph] {msg}", flush=True)


def _normalize_url(url: str) -> str:
    """Canonical form for dedup: lowercase scheme+host, drop fragment, no trailing
    slash. So http://x/a, http://x/a/, and http://x/a#top count as one page."""
    p = urlparse(url)
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def build_agent_graph(session, llm, observer, config: AppConfig | None = None,
                      *, evidence_dir: Path | None = None):
    cfg = config or AppConfig()
    gate = SafetyGate(
        llm,
        allow_all=cfg.allow_all,
        block_uncertain=cfg.block_uncertain,
        extra_blocked=tuple(cfg.blocked_button_text),
    )
    testgen = TestCaseGenerator(llm)
    runner = TestRunner(
        session, gate, observer,
        evidence_dir=evidence_dir, capture_screenshots=cfg.capture_screenshots,
    )
    modal_tester = ModalTester(
        session, gate, observer, testgen,
        evidence_dir=evidence_dir, capture_screenshots=cfg.capture_screenshots,
    )
    blocked_patterns = cfg.all_blocked_url_patterns()

    def _allowed_host(host: str, seed_host: str) -> bool:
        if host == seed_host:
            return True
        return any(host == d.lower() or host.endswith("." + d.lower()) for d in cfg.allowed_domains)

    async def snapshot_node(state: AgentState) -> AgentState:
        target = state.get("next_url") or state["seed_url"]
        _log(f"→ snapshot: {target}")
        await session.goto(target)
        page = session.page
        elements = await session.extract_elements()
        summary = await session.summary()

        seed_host = urlparse(state["seed_url"]).netloc.lower()
        raw = await page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
        links = []
        for u in raw:
            host = urlparse(u).netloc.lower()
            if _allowed_host(host, seed_host) and not url_is_blocked(u, blocked_patterns):
                links.append(_normalize_url(u))
        links = list(dict.fromkeys(links))
        # Record where we ACTUALLY landed (post-redirect), normalized, so a redirect
        # can't make us re-crawl the same page under two different spellings.
        landed = _normalize_url(page.url)
        _log(f"  snapshot ok: {len(elements)} elements, {len(links)} links")
        return {
            "current_url": page.url,
            "summary": summary,
            "elements": elements,
            "links": links,
            "visited_urls": [landed],
            "iteration": state.get("iteration", 0) + 1,
        }

    async def context_node(state: AgentState) -> AgentState:
        _log("→ infer_context (LLM call) …")
        blob = build_context_blob(state["summary"], state["elements"])
        context = await infer_context(llm, blob)
        _log("  infer_context ok")

        override = state.get("locale") or cfg.locale
        if override:
            context.country_hint = override
        elif not context.country_hint:
            context.country_hint = DEFAULT_COUNTRY
        return {"context": context}

    async def plan_node(state: AgentState) -> AgentState:
        # No submittable form on this page (e.g. a read-only list/table) — nothing for
        # the test engine to fill + submit, so skip it. The modal scan still runs.
        if find_submit(state["elements"]) is None:
            _log("→ plan: no submittable form, skipping")
            return {"test_cases": []}
        _log("→ plan: generating test cases (LLM call) …")
        # The test-case LLM call can fail — transient errors, or invalid/oversized JSON
        # on big forms. Don't let that abort the crawl: skip this page's suite, keep going.
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
        # 2. any forms hidden behind launcher buttons (modals)
        results += await modal_tester.run(url, state.get("context"))
        _log(f"  execute ok: {len(results)} result(s)")
        return {"test_results": results} if results else {}

    async def observe_node(state: AgentState) -> AgentState:
        # Passive JS/network errors only. We deliberately do NOT run check_page() here:
        # after a whole execute phase the DOM still shows :invalid fields from the last
        # case WE submitted, which would be mis-reported as a page-level bug. Validation
        # is judged per-case inside the runner instead.
        _log("→ observe")
        return {"findings": observer.collect_errors()}

    async def decide_node(state):
        _log("→ decide: choosing next page")
        visited = set(state.get("visited_urls", []))
        frontier = list(state.get("frontier", []))

        # Add newly discovered links (already normalized + host/blocklist filtered).
        for url in state.get("links", []):
            if url not in visited and url not in frontier:
                frontier.append(url)

        # Cross off anything we've since visited, and re-check the blocklist (the seed
        # frontier from config routes hasn't been filtered yet).
        frontier = [
            u for u in frontier
            if _normalize_url(u) not in visited and not url_is_blocked(u, blocked_patterns)
        ]

        # Breadth-first: take from the front, respecting the crawl-lap cap.
        if frontier and state.get("iteration", 0) < cfg.max_iterations:
            next_url = frontier.pop(0)
            return {"next_url": next_url, "frontier": frontier}

        return {"next_url": None, "frontier": frontier}

    def route(state):
        return "snapshot" if state.get("next_url") else END

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

    return g.compile()
