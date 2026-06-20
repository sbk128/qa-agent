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
uv sync
uv run playwright install chromium
cp .env .env.local  # then fill in GROQ_API_KEY
```

Phase 0 entry point (once implemented):

```bash
python -m src.main --url https://example.com
```
