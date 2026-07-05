"""CLI entry point.

    python -m src.main --url http://localhost:5173
    python -m src.main --config configs/example.yaml
    python -m src.main --url http://host --headless --json-out result.json

Exit codes (for CI): 0 = clean, 2 = findings worth attention, 1 = the run itself failed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from rich.console import Console

from src.config import AppConfig, load_config

console = Console()


def _build_config(args) -> AppConfig:
    cfg = load_config(args.config) if args.config else AppConfig()
    # CLI flags override the config file where provided.
    if args.url:
        cfg.url = args.url
    if args.provider:
        cfg.provider = args.provider
    if args.locale:
        cfg.locale = args.locale
    if args.auth:
        cfg.auth_path = args.auth
    if args.max_pages is not None:
        cfg.max_iterations = args.max_pages
    if args.report_dir:
        cfg.report_dir = args.report_dir
    if args.headless:
        cfg.headless = True
    if args.allow_all:
        cfg.allow_all = True
    return cfg


def _has_session(path: str | None) -> bool:
    if not path:
        return False
    p = Path(path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except Exception:
        return False
    return bool(data.get("cookies") or data.get("origins"))


async def _run(cfg: AppConfig) -> int:
    from src.agent.agent_graph import build_agent_graph
    from src.agent.observer import Observer
    from src.browser.session import BrowserSession
    from src.llm import get_provider
    from src.reporting.report import write_report

    seed_host = urlparse(cfg.url).netloc
    run_dir = Path(cfg.report_dir) / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    evidence_dir = run_dir / "evidence"
    started = datetime.now()

    storage_state = cfg.auth_path if _has_session(cfg.auth_path) else None
    if cfg.auth_path and not storage_state:
        console.print(f"[yellow]⚠ {cfg.auth_path} has no session data — running unauthenticated.[/]")

    llm = get_provider(cfg.provider)
    if cfg.allow_all:
        console.print("[yellow]⚠ --allow-all: safety gate disabled (sandbox mode).[/]")

    # Accumulate state as it streams so a crash mid-crawl still yields a partial report.
    acc: dict = {"visited_urls": [], "findings": [], "test_results": []}

    def absorb(delta: dict) -> None:
        if not isinstance(delta, dict):
            return
        for u in delta.get("visited_urls", []) or []:
            if u not in acc["visited_urls"]:
                acc["visited_urls"].append(u)
        acc["findings"].extend(delta.get("findings", []) or [])
        acc["test_results"].extend(delta.get("test_results", []) or [])

    crashed: Exception | None = None
    async with BrowserSession(headless=cfg.headless, storage_state=storage_state) as session:
        observer = Observer(session.page, app_host=seed_host)
        if cfg.capture_trace:
            await session.start_tracing()
        app = build_agent_graph(session, llm, observer, cfg, evidence_dir=evidence_dir)
        initial = {
            "seed_url": cfg.url,
            "visited_urls": [],
            "findings": [],
            "frontier": list(cfg.routes),
            "iteration": 0,
            "test_results": [],
            "locale": cfg.locale,
        }
        recursion_limit = max(150, cfg.max_iterations * 6 + 30)
        try:
            async for chunk in app.astream(
                initial, config={"recursion_limit": recursion_limit}, stream_mode="updates"
            ):
                for node, delta in chunk.items():
                    console.print(f"[dim]· {node}[/]")
                    absorb(delta)
        except Exception as e:  # keep whatever we accumulated
            crashed = e
            console.print(f"[red]Run failed mid-crawl: {e}[/]")
        finally:
            if cfg.capture_trace:
                try:
                    await session.stop_tracing(run_dir / "trace.zip")
                except Exception:
                    pass
        await _aclose_llm(llm)

    meta = {
        "target": cfg.url,
        "provider": cfg.provider,
        "model": getattr(llm, "_default_model", None),
        "locale": cfg.locale,
        "allow_all": cfg.allow_all,
        "started": started.strftime("%Y-%m-%d %H:%M:%S"),
        "duration": f"{time.time() - started.timestamp():.0f}s",
        "crashed": str(crashed) if crashed else None,
    }
    out = write_report(acc, run_dir=run_dir, meta=meta)

    results = acc["test_results"]
    passed = sum(1 for r in results if r.status == "pass")
    scored = sum(1 for r in results if r.counts_toward_score)
    worth = sum(1 for r in results if r.status == "review" and
                any(f.category in ("network_error", "js_error") for f in r.findings))
    high = sum(1 for f in acc["findings"] if getattr(f, "severity", "") in ("critical", "high"))

    console.print(f"\n[bold]Report:[/] {out / 'report.md'}")
    console.print(f"Tests: {passed}/{scored} passed · {worth} worth checking · {high} high/critical finding(s)")

    if crashed:
        return 1
    return 2 if (worth or high) else 0


async def _aclose_llm(llm) -> None:
    client = getattr(llm, "_client", None)
    if client is None:
        return
    for name in ("aclose", "close"):
        fn = getattr(client, name, None)
        if fn is None:
            continue
        try:
            await fn()
        except Exception:
            pass
        return


def main() -> int:
    load_dotenv(".env")
    load_dotenv(".env.local", override=True)

    parser = argparse.ArgumentParser(prog="qa-agent", description="Autonomous web QA agent.")
    parser.add_argument("--url", help="Seed URL to crawl and test.")
    parser.add_argument("--config", help="YAML config (see configs/example.yaml). CLI flags override it.")
    parser.add_argument("--provider", choices=["groq", "ollama"], help="LLM backend.")
    parser.add_argument("--locale", help="Locale hint, e.g. IN or US.")
    parser.add_argument("--auth", help="Saved storage_state JSON from scripts/login.py.")
    parser.add_argument("--max-pages", type=int, help="Crawl-lap cap (overrides config).")
    parser.add_argument("--report-dir", help="Where to write reports (default: reports/).")
    parser.add_argument("--headless", action="store_true", help="Run the browser headless.")
    parser.add_argument("--allow-all", action="store_true", help="Sandbox: disable the destructive safety gate.")
    parser.add_argument("--json-out", help="Also copy report.json to this path (for CI).")
    args = parser.parse_args()

    cfg = _build_config(args)
    if not cfg.url:
        parser.error("a target URL is required (pass --url or set target.url in --config)")

    code = asyncio.run(_run(cfg))

    if args.json_out:
        # Copy the machine-readable report to a stable path for CI to pick up.
        try:
            latest = sorted(Path(cfg.report_dir).glob("run-*/report.json"))[-1]
            Path(args.json_out).write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as e:
            console.print(f"[yellow]Could not copy json-out: {e}[/]")
    return code


if __name__ == "__main__":
    sys.exit(main())
