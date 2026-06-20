"""CLI entry point: `python -m src.main --url ...`."""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console

from src.agent import build_graph

console = Console()


async def _run(url: str) -> int:
    graph = build_graph()
    result = await graph.ainvoke({"url": url})
    console.print(f"[bold green]Description:[/] {result['description']}")
    console.print(f"[dim]Screenshot: {result['screenshot_path']}[/]")
    return 0


def main() -> int:
    # .env.local wins over .env so secrets can stay out of the committed file.
    load_dotenv(".env")
    load_dotenv(".env.local", override=True)

    parser = argparse.ArgumentParser(prog="qa-agent")
    parser.add_argument("--url", required=True, help="URL to open and describe")
    args = parser.parse_args()
    return asyncio.run(_run(args.url))


if __name__ == "__main__":
    sys.exit(main())
