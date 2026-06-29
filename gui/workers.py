"""Background workers that drive the async agent from the Qt GUI thread.

Qt has its own event loop; the agent (Playwright + LangGraph + Groq) is asyncio.
The bridge: each worker is a QObject moved onto its own QThread, where it spins up
a private asyncio loop with `asyncio.run(...)`. Results flow back to the GUI via Qt
signals, which Qt delivers safely across threads (queued connections).

Two workers:
  - RunWorker   — runs a full crawl, streaming node-by-node progress.
  - LoginWorker — opens a headed browser so you can log in by hand, then saves
                  the session to `auth.json` (no test agent involved).
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from gui.paths import PROJECT_ROOT, REPORTS_DIR, has_saved_session, load_env


# --------------------------------------------------------------------------- #
# Log capture
# --------------------------------------------------------------------------- #
class _SignalStream:
    """A file-like object that forwards everything written to it to a Qt signal.

    The agent and its dependencies (Groq retry logs, the runner's reload notes,
    the executor's `[mui_select]` prints) all write to stdout/stderr. We redirect
    those streams to this object during a run so every line shows up in the GUI
    log console. `emit` is a bound Qt Signal.emit, so delivery is thread-safe.
    """

    def __init__(self, emit, mirror=None) -> None:
        self._emit = emit
        self._mirror = mirror  # keep echoing to the real terminal too
        self._buffer = ""

    def write(self, text: str) -> int:
        if self._mirror is not None:
            try:
                self._mirror.write(text)
            except Exception:
                pass
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._emit(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""
        if self._mirror is not None:
            try:
                self._mirror.flush()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Run configuration
# --------------------------------------------------------------------------- #
@dataclass
class RunConfig:
    url: str
    routes: list[str] = field(default_factory=list)   # extra pages to test directly
    locale: str | None = None
    auth_path: Path | None = None      # saved session (auth.json) or None
    headless: bool = False             # show the browser by default — it's the point
    max_iterations: int = 12           # crawl depth cap (overrides agent_graph default)
    allow_all: bool = False            # sandbox: disable the destructive safety gate


# --------------------------------------------------------------------------- #
# RunWorker — the crawl
# --------------------------------------------------------------------------- #
class RunWorker(QObject):
    """Runs one crawl and streams progress.

    Signals:
      log(str)            — a line of agent output for the console.
      status(str)         — short status text (e.g. "Running node: plan").
      progress(dict)      — accumulated display state after each graph step.
      finished(dict)      — final summary incl. the written report path.
      failed(str)         — an unrecoverable error (with traceback in the message).
    """

    log = Signal(str)
    status = Signal(str)
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, config: RunConfig) -> None:
        super().__init__()
        self._cfg = config
        self._stop = False
        # Set once the async run is live, so Stop (called from the GUI thread) can
        # cancel the in-flight task instead of waiting for the current node to end.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream_task: asyncio.Task | None = None

        # Accumulated, GUI-facing state. We keep the real pydantic objects for the
        # final report, and emit plain dicts (model_dump) to the GUI so the two
        # threads never share live model instances.
        self._visited: list[str] = []
        self._findings = []        # list[Finding]
        self._test_results = []    # list[TestResult]
        self._latest_cases = []    # list[TestCase] for the current page
        self._context = None
        self._iteration = 0
        self._current_url = ""

    @Slot()
    def request_stop(self) -> None:
        # Called from the GUI thread. Setting the flag alone would only take effect
        # at the next node boundary (a node like execute_node can run a whole test
        # suite first). So we also cancel the running task: that raises CancelledError
        # straight through the in-flight Playwright await, unwinding it immediately.
        self._stop = True
        self.status.emit("Stopping…")
        loop, task = self._loop, self._stream_task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    @Slot()
    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception:
            self.failed.emit(traceback.format_exc())

    # -- internals ---------------------------------------------------------- #
    def _emit_progress(self, node: str) -> None:
        self.progress.emit(
            {
                "node": node,
                "iteration": self._iteration,
                "current_url": self._current_url,
                "visited": list(self._visited),
                "findings": [f.model_dump() for f in self._findings],
                "test_results": [r.model_dump() for r in self._test_results],
                "test_cases": [c.model_dump() for c in self._latest_cases],
                "context": self._context.model_dump() if self._context else None,
            }
        )

    async def _consume(self, app, initial: dict, recursion_limit: int) -> None:
        # `updates` stream mode yields {node_name: delta} after each node, giving us
        # both the node label and its incremental output. Cancelling this task (via
        # request_stop) interrupts whatever Playwright call is currently awaiting.
        async for chunk in app.astream(
            initial, config={"recursion_limit": recursion_limit}, stream_mode="updates"
        ):
            for node, delta in chunk.items():
                self._absorb(node, delta)
                self.status.emit(f"Running: {node}")
                self._emit_progress(node)

    async def _run(self) -> None:
        load_env()
        self._loop = asyncio.get_running_loop()

        # Imported here (not at module load) so the GUI still starts even if a
        # heavy/optional dependency is missing — the error surfaces at run time.
        import src.agent.agent_graph as agent_graph
        from src.agent.agent_graph import build_agent_graph
        from src.agent.observer import Observer
        from src.browser.session import BrowserSession
        from src.llm import get_provider
        from src.reporting.report import write_report

        cfg = self._cfg

        # Override the module-level crawl cap with the value chosen in the UI.
        agent_graph.MAX_ITERATIONS = cfg.max_iterations

        storage_state = None
        if cfg.auth_path and has_saved_session(cfg.auth_path):
            storage_state = str(cfg.auth_path)
            self.log.emit(f"Using saved session: {cfg.auth_path}")
        elif cfg.auth_path and Path(cfg.auth_path).exists():
            self.log.emit(
                f"⚠️  {cfg.auth_path} has no session data — continuing unauthenticated. "
                f"Use 'Capture Login' first if this page needs auth."
            )

        self.status.emit("Launching browser…")
        llm = get_provider()  # raises a clear error if GROQ_API_KEY is missing

        # ~6 graph nodes per crawl lap; give recursion headroom beyond the cap.
        recursion_limit = max(150, cfg.max_iterations * 6 + 30)

        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = _SignalStream(self.log.emit, mirror=old_out)
        sys.stderr = _SignalStream(self.log.emit, mirror=old_err)
        try:
            async with BrowserSession(headless=cfg.headless, storage_state=storage_state) as session:
                observer = Observer(session.page)
                if cfg.allow_all:
                    self.log.emit("⚠️  --allow-all: safety gate disabled (sandbox mode).")
                app = build_agent_graph(session, llm, observer, allow_all=cfg.allow_all)

                initial = {
                    "seed_url": cfg.url,
                    "visited_urls": [],
                    "action_history": [],
                    "findings": [],
                    # Seed the frontier with any user-listed routes so the agent
                    # visits them even though this SPA exposes no <a href> links.
                    "frontier": list(cfg.routes),
                    "iteration": 0,
                    "test_results": [],
                    "locale": cfg.locale,
                }

                self.status.emit("Crawling…")
                # Run the crawl as a child task so Stop can cancel it mid-node.
                self._stream_task = asyncio.ensure_future(
                    self._consume(app, initial, recursion_limit)
                )
                try:
                    await self._stream_task
                except asyncio.CancelledError:
                    # Stop was pressed: unwind cleanly and still report what we have.
                    self._stop = True
                    self.log.emit("Run stopped by user.")

                # Build the state dict write_report expects from what we accumulated.
                final_state = {
                    "visited_urls": self._visited,
                    "action_history": [],
                    "findings": self._findings,
                    "test_results": self._test_results,
                }
                out_dir = write_report(final_state, out_dir=str(REPORTS_DIR))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            # Close the Groq SDK's httpx client *now*, while this run's event loop
            # is still alive. Otherwise Python GC-closes it later on a dead loop and
            # prints a noisy "RuntimeError: Event loop is closed" traceback.
            await self._aclose_llm(llm)

        passed = sum(1 for r in self._test_results if r.passed)
        summary = {
            "report_dir": str(out_dir),
            "report_md": str(Path(out_dir) / "report.md"),
            "stopped": self._stop,
            "iterations": self._iteration,
            "visited": list(self._visited),
            "findings": [f.model_dump() for f in self._findings],
            "test_results": [r.model_dump() for r in self._test_results],
            "tests_passed": passed,
            "tests_total": len(self._test_results),
        }
        self.status.emit("Done" if not self._stop else "Stopped")
        self.finished.emit(summary)

    @staticmethod
    async def _aclose_llm(llm) -> None:
        """Best-effort close of the provider's underlying async HTTP client."""
        client = getattr(llm, "_client", None)
        if client is None:
            return
        for name in ("close", "aclose"):
            fn = getattr(client, name, None)
            if fn is None:
                continue
            try:
                await fn()
            except Exception:
                pass
            return

    def _absorb(self, node: str, delta: dict) -> None:
        """Fold one node's output delta into our running display state.

        In `updates` stream mode each value is exactly what the node returned (the
        delta, before LangGraph's reducers run), so list fields accumulate here.
        """
        if not isinstance(delta, dict):
            return
        if "iteration" in delta:
            self._iteration = max(self._iteration, delta["iteration"] or 0)
        if delta.get("current_url"):
            self._current_url = delta["current_url"]
        if "context" in delta and delta["context"] is not None:
            self._context = delta["context"]
        if "test_cases" in delta:
            self._latest_cases = delta["test_cases"] or []
        for url in delta.get("visited_urls", []) or []:
            if url not in self._visited:
                self._visited.append(url)
        self._findings.extend(delta.get("findings", []) or [])
        self._test_results.extend(delta.get("test_results", []) or [])


# --------------------------------------------------------------------------- #
# LoginWorker — capture an authenticated session
# --------------------------------------------------------------------------- #
class LoginWorker(QObject):
    """Opens a headed browser at a login page and waits for a manual login.

    Completion is whichever comes first: the page navigates away from `/login`,
    or the user clicks "I've logged in" in the GUI (which calls `mark_done`).
    Then cookies + localStorage (incl. the JWT) are saved via Playwright
    storage_state. The test agent never touches the login form.
    """

    log = Signal(str)
    status = Signal(str)
    finished = Signal(dict)   # {path, cookies, origins, looks_empty}
    failed = Signal(str)

    def __init__(self, url: str, auth_path: Path) -> None:
        super().__init__()
        self._url = url
        self._auth_path = auth_path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._done: asyncio.Event | None = None

    @Slot()
    def mark_done(self) -> None:
        """Called from the GUI thread when the user says they're logged in."""
        if self._loop and self._done:
            self._loop.call_soon_threadsafe(self._done.set)

    @Slot()
    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception:
            self.failed.emit(traceback.format_exc())

    async def _run(self) -> None:
        load_env()
        from src.browser.session import BrowserSession

        self._loop = asyncio.get_running_loop()
        self._done = asyncio.Event()

        async with BrowserSession(headless=False) as session:
            page = session.page
            self.status.emit("Opening login page…")
            await session.goto(self._url)
            self.status.emit("Waiting for you to log in…")
            self.log.emit("Log in inside the browser window, then click 'I've logged in'.")

            left_login = asyncio.create_task(
                page.wait_for_url(lambda u: "login" not in u.lower(), timeout=0)
            )
            clicked_done = asyncio.create_task(self._done.wait())
            _, pending = await asyncio.wait(
                {left_login, clicked_done}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            saved = await session.save_storage_state(self._auth_path)

        import json

        data = json.loads(Path(saved).read_text())
        n_cookies = len(data.get("cookies", []))
        n_origins = len(data.get("origins", []))
        looks_empty = n_cookies == 0 and n_origins == 0
        self.finished.emit(
            {
                "path": str(saved),
                "cookies": n_cookies,
                "origins": n_origins,
                "looks_empty": looks_empty,
            }
        )
