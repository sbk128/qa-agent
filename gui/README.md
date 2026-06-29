# QA Agent — Desktop GUI

A PySide6 (Qt) front-end for the agent in `src/`. It lets you configure and
launch a crawl, watch it run live, capture a login session, and browse past
reports — without touching the command line.

## Run it

```bash
uv sync --group gui                 # installs PySide6
uv run qa-agent-gui                 # launch the app
# or
uv run python -m gui.app
```

You still need a Groq key. Either add it in the in-app **Settings** dialog
(saved to `.env.local`, gitignored) or set `GROQ_API_KEY` in `.env`.

## What's where

| File | Role |
|---|---|
| `app.py` | Entry point — builds the `QApplication`, applies the theme. |
| `main_window.py` | The whole window: config form, stat cards, result tabs, history. |
| `workers.py` | `RunWorker` / `LoginWorker` — run the async agent on a background QThread and stream results back via Qt signals. |
| `widgets.py` | Result panels: stat cards, findings table, test-results tree, coverage list. |
| `dialogs.py` | Settings dialog + the manual-login capture dialog. |
| `report_loader.py` | Reads past `reports/run-*/report.json` for the History panel. |
| `paths.py` | Project paths + `.env` helpers (key status, writing `.env.local`). |
| `theme.py` | One dark stylesheet + the severity/outcome colour map. |

## How it maps to the agent

- **Run** → builds `RunConfig`, then `RunWorker` drives `build_agent_graph(...)`
  via `app.astream(..., stream_mode="updates")`. Each node's output is folded
  into the live views (findings, test results, coverage), and `write_report`
  writes the same `reports/run-*` folder the CLI produces.
- **Capture Login** → `LoginWorker` opens a headed browser (no agent), waits for
  you to log in, then saves `auth.json` via Playwright `storage_state` — the same
  thing `scripts/login.py` does, but with a button instead of pressing Enter.
- **History** → each past run's `report.json` renders through the *same* widgets
  as a live run.

## Notes / things you may want to change

- **Max pages** in the UI overrides `agent_graph.MAX_ITERATIONS` for that run.
- The browser is shown by default (tick *headless* to hide it).
- `action_history` isn't populated by the current graph, so "Actions taken"
  stays 0 — that matches the CLI today; wire it up in the graph if you want it.
