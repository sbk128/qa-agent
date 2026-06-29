from collections import defaultdict
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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


# --- small rendering helpers (turn raw data into something a human can read) ---

def _short_field(selector: str) -> str:
    """Pull a readable field name out of an ugly selector.

    e.g. 'input[name="firstName"]' -> 'firstName', '#age' -> 'age'.
    """
    for pat in (r'\[name="([^"]+)"\]', r'\[data-testid="([^"]+)"\]', r'#([\w-]+)'):
        m = re.search(pat, selector)
        if m:
            return m.group(1)
    return selector if len(selector) <= 30 else selector[:27] + "…"


def _short_value(v: str) -> str:
    """A compact, safe display of a value we typed into a field."""
    if v is None:
        return "(none)"
    if v == "":
        return "(blank)"
    if v.strip() == "":
        return "(whitespace)"
    shown = v.replace("\n", " ").replace("\r", " ")
    n = len(v)
    if n > 40:
        return f'"{shown[:12]}…" ({n} chars)'
    return f'"{shown}"'


def _typed(case) -> str:
    """One compact line of what the robot actually filled in."""
    if not case.field_values:
        return "(nothing filled)"
    return ", ".join(
        f"{_short_field(s)}={_short_value(val)}" for s, val in case.field_values.items()
    )


def _server_note(result) -> str:
    """If the server answered with a 4xx/5xx during this case, surface it."""
    statuses = []
    for f in result.findings:
        if f.category == "network_error":
            first = f.description.split()[0] if f.description else ""
            if first.isdigit():
                statuses.append(first)
    return f"server replied {', '.join(statuses)}" if statuses else ""


def _has_hard_evidence(result) -> bool:
    """True if the app itself complained during this case — the server returned
    a 4xx/5xx, or a script crashed. That's concrete proof something is off,
    independent of the robot's *guess* about what should have happened.
    """
    return any(f.category in ("network_error", "js_error") for f in result.findings)


def build_report(state) -> str:
    findings = state.get("findings", [])
    visited = state.get("visited_urls", [])
    results = state.get("test_results", [])

    L = []

    # ---- header: the one-line "what happened" ----
    sample_url = visited[0] if visited else (results[0].url if results else "")
    host = urlparse(sample_url).netloc or sample_url
    passed = sum(r.passed for r in results)
    total = len(results)
    when = datetime.now().strftime("%d %b %Y")

    bits = [b for b in (host, f"{len(visited)} pages") if b]
    if total:
        bits.append(f"{passed}/{total} checks behaved as expected")
    L.append("# QA Test Report")
    L.append(f"_{' · '.join(bits)} · {when}_")
    L.append("")

    # ---- sort results into three buckets ----
    review = [r for r in results if not r.passed and r.observed != "error"]
    errored = [r for r in results if r.observed == "error"]

    # ---- 1. flagged cases, split by how much we actually trust them ----
    # "worth" = the app gave a concrete error (hard evidence). "maybe" = the form
    # just didn't match the robot's guess, with nothing actually broken (soft).
    worth = [r for r in review if _has_hard_evidence(r)]
    maybe = [r for r in review if not _has_hard_evidence(r)]

    L.append(f"## ⚠ Worth checking  ({len(worth)})")
    L.append(
        "The form did something unexpected AND the app gave a concrete error "
        "— the server rejected it, or a script crashed. Strong signal.\n"
    )
    if not worth:
        L.append("_Nothing with hard evidence this run._")
        L.append("")
    else:
        for i, r in enumerate(worth, 1):
            note = _server_note(r) or "app/script error"
            L.append(f'{i}. **{r.url}** — "{r.case.name}"')
            L.append(f"   - We typed: {_typed(r.case)}")
            L.append(f"   - Expected: **{r.case.expected}**   Got: **{r.observed}**  ({note})")
        L.append("")

    if maybe:
        L.append(f"## 🤔 Maybe — unmet guess, no error  ({len(maybe)})")
        L.append(
            "The form accepted (or rejected) something the robot only *guessed* about, "
            "and nothing actually errored. Usually a permissive form or an over-strict "
            "guess — skim these, don't trust them.\n"
        )
        for r in maybe:
            L.append(
                f'- {r.url} — "{r.case.name}"  '
                f"(expected {r.case.expected}, got {r.observed})"
            )
        L.append("")

    # ---- 2. every check, grouped by form, with the data we typed ----
    L.append("## Results by form")
    if not results:
        L.append("_No forms were tested._")
        L.append("")
    else:
        by_url = defaultdict(list)
        for r in results:
            by_url[r.url].append(r)
        for url, page_results in by_url.items():
            page_passed = sum(r.passed for r in page_results)
            L.append(f"### {url} — {page_passed}/{len(page_results)} ok")
            L.append("| Check | We typed | Should | Did | OK |")
            L.append("|---|---|---|---|---|")
            for r in page_results:
                ok = "✓" if r.passed else ("⚠" if r.observed != "error" else "✗")
                typed = _typed(r.case).replace("|", "\\|")
                L.append(
                    f"| {r.case.name} | {typed} | {r.case.expected} "
                    f"| {r.observed} | {ok} |"
                )
            L.append("")

    # ---- 3. cases the robot couldn't finish ----
    if errored:
        L.append(f"## Couldn't complete  ({len(errored)})")
        L.append(
            "_Page failed to load, submit didn't fire, or the server errored (5xx)._\n"
        )
        for r in errored:
            note = _server_note(r)
            note = f" — {note}" if note else ""
            L.append(f'- {r.url} — "{r.case.name}"{note}')
        L.append("")

    # ---- 4. genuine app errors the robot tripped over (crashes / JS errors) ----
    crashes = [f for f in findings if f.category == "js_error"]
    if crashes:
        groups: dict = {}
        for f in crashes:
            key = (f.severity, f.description, f.url)
            groups.setdefault(key, {"f": f, "n": 0})
            groups[key]["n"] += 1
        ordered = sorted(
            groups.values(), key=lambda g: _SEVERITY_ORDER.get(g["f"].severity, 99)
        )
        L.append("## Errors the robot hit")
        for g in ordered:
            f = g["f"]
            times = f" (×{g['n']})" if g["n"] > 1 else ""
            L.append(f"- **[{f.severity}]** {f.title}{times} — {f.description[:200]}")
        L.append("")

    # ---- 5. coverage, demoted to the bottom as reference ----
    L.append("## Pages tested")
    if visited:
        for url in visited:
            p = urlparse(url)
            path = p.path or url
            if p.query:
                path += f"?{p.query}"
            L.append(f"- {path}")
    else:
        L.append("_None recorded._")

    return "\n".join(L)
