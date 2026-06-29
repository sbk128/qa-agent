"""Desktop GUI for the qa-agent.

A PySide6 (Qt) front-end that wraps the existing LangGraph agent so you can:
  - configure and launch a crawl (URL, locale, auth session, headless, depth),
  - watch it run live (status, log, findings + test results as they accumulate),
  - capture an authenticated session for pages behind a login,
  - browse and re-open past reports written to `reports/run-*`.

The GUI is a thin shell: all the real work still happens in `src/` (the agent
graph, browser session, runner, reporting). See `gui/workers.py` for how the
async agent is driven from a Qt background thread.
"""
