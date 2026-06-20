from collections import defaultdict
import json
from datetime import datetime
from pathlib import Path

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

def write_report(state, out_dir="reports") -> Path:
    run = Path(out_dir) / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)

    (run / "report.md").write_text(build_report(state))

    data = {
        "visited_urls": state.get("visited_urls", []),
        "action_history": [a.model_dump() for a in state.get("action_history", [])],
        "findings": [f.model_dump() for f in state.get("findings", [])],
        "test_results": [r.model_dump() for r in state.get("test_results", [])],
    }
    (run / "report.json").write_text(json.dumps(data, indent=2))
    return run

def build_report(state) -> str:
    findings = state.get("findings", [])
    visited = state.get("visited_urls", [])
    actions = state.get("action_history", [])
    results = state.get("test_results", [])

    groups: dict = {}
    for f in findings:
        key = (f.severity, f.category, f.description, f.url)
        if key not in groups:
            groups[key] = {"finding": f, "count": 0}
        groups[key]["count"] += 1

    unique = sorted(
        groups.values(),
        key=lambda g: _SEVERITY_ORDER.get(g["finding"].severity, 99)
    )

    tally = defaultdict(int)
    for g in unique:
        tally[g["finding"].severity] += 1

    L = []
    L.append("# QA Agent Report\n")
    L.append("## Summary")
    L.append(f"- Pages visited: **{len(visited)}**")
    L.append(f"- Actions taken: **{len(actions)}**")
    L.append(f"- Findings: **{len(unique)}** unique (from {len(findings)} raw)")
    for sev in ["critical", "high", "medium", "low", "info"]:
        if tally[sev]:
            L.append(f"  - {sev}: {tally[sev]}")
    L.append("")

    L.append("## Coverage — pages visited")
    for url in visited:
        L.append(f"- {url}")
    L.append("")

    L.append("## Findings")
    if not unique:
        L.append("_No findings._")
    for g in unique:
        f = g["finding"]
        times = f" (×{g['count']})" if g["count"] > 1 else ""
        L.append(f"### [{f.severity.upper()}] {f.title}{times}")
        L.append(f"- Category: `{f.category}`")
        L.append(f"- URL: {f.url}")
        L.append(f"- {f.description}")
        L.append("")

    # --- Test Results section (only if the agent ran any) ---
    if results:
        passed = sum(r.passed for r in results)
        L.append("## Test Results")
        L.append(f"**{passed}/{len(results)} cases passed**\n")

        by_url = defaultdict(list)
        for r in results:
            by_url[r.url].append(r)

        for url, page_results in by_url.items():
            page_passed = sum(r.passed for r in page_results)
            L.append(f"### {url}  —  {page_passed}/{len(page_results)} passed")
            for r in page_results:
                mark = "✓" if r.passed else "✗ **review**"
                L.append(f"- {mark} `[{r.case.category}]` **{r.case.name}** — {r.detail}")
            L.append("")

    return "\n".join(L)