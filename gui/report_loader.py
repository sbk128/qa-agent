"""Read past runs back off disk for the History panel.

A run is a `reports/run-YYYYMMDD-HHMMSS/` folder holding `report.json`
(machine-readable) and `report.md` (the rendered report). The JSON already
matches the dict shape the result widgets expect, so loading is trivial.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gui.paths import REPORTS_DIR


@dataclass
class RunReport:
    path: Path
    name: str
    when: datetime | None
    visited_urls: list[str]
    findings: list[dict]
    test_results: list[dict]
    markdown: str

    @property
    def tests_passed(self) -> int:
        return sum(1 for r in self.test_results if r.get("passed"))

    @property
    def label(self) -> str:
        when = self.when.strftime("%b %d, %Y  %H:%M") if self.when else self.name
        return f"{when}   ·   {len(self.findings)} findings · {self.tests_passed}/{len(self.test_results)} passed"


def _parse_when(name: str) -> datetime | None:
    # folders look like "run-20260624-224430"
    try:
        return datetime.strptime(name, "run-%Y%m%d-%H%M%S")
    except ValueError:
        return None


def list_runs() -> list[RunReport]:
    """Newest first. Skips folders without a readable report.json."""
    if not REPORTS_DIR.exists():
        return []
    runs: list[RunReport] = []
    for folder in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        report = load_run(folder)
        if report is not None:
            runs.append(report)
    return runs


def load_run(folder: Path) -> RunReport | None:
    json_path = folder / "report.json"
    if not json_path.exists():
        return None
    try:
        # utf-8: reports hold emoji/symbols; the Windows default codec chokes.
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    md_path = folder / "report.md"
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return RunReport(
        path=folder,
        name=folder.name,
        when=_parse_when(folder.name),
        visited_urls=data.get("visited_urls", []),
        findings=data.get("findings", []),
        test_results=data.get("test_results", []),
        markdown=markdown,
    )
