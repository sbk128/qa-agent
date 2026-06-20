# qa-agent

Autonomous QA testing agent. Given a URL, scans any web application, generates
realistic + adversarial data, drives the page, captures errors, and produces a
QA report.

Build plan lives in [`qa_agent_plan_v2.md`](../qa_agent_plan_v2.md). This repo
follows the phased structure in that document.

## Layout

```
src/
  agent/       LangGraph nodes
  browser/     Playwright wrappers + snapshotter
  llm/         Provider abstraction (Groq, ...)
  safety/      Destructive action detection
  data/        Generators + edge case library
  models/      Pydantic schemas
  reporting/   Report generator
  config.py
  main.py
tests/
configs/       YAML configs per target
reports/       Generated reports (gitignored)
screenshots/   Captured screenshots (gitignored)
```

## Getting started

```bash
uv sync                              # install dependencies (uses uv.lock)
uv run playwright install chromium   # install the browser
cp .env.example .env                 # then open .env and fill in GROQ_API_KEY
```

Phase 0 entry point (once implemented):

```bash
python -m src.main --url https://example.com
```

## Working across devices

Clone, install, and recreate your local secrets:

```bash
git clone https://github.com/sbk128/qa-agent.git
cd qa-agent
uv sync
uv run playwright install chromium
cp .env.example .env                 # fill in your GROQ_API_KEY
```

`.env` (and `.env.local`) are gitignored, so your API key never leaves your
machine. Commit and push your work before switching devices, and `git pull` on
the other side to stay in sync.
