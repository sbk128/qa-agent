import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def write_report(state, out_dir="reports", run_dir=None, meta=None) -> Path:
    """Write report.md + report.json.

    `run_dir` lets the caller pre-create the run folder (so per-case screenshots can
    be written into it during the run and linked from the report). `meta` is a dict of
    run metadata (target, provider, model, duration…) rendered at the top of the report.
    """
    run = Path(run_dir) if run_dir else Path(out_dir) / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    meta = meta or {}

    # encoding="utf-8": the report contains ⚠ 🤔 ✓ ✗ etc., which the Windows default
    # (cp1252) can't encode — without this, write_text raises UnicodeEncodeError.
    (run / "report.md").write_text(build_report(state, meta), encoding="utf-8")

    data = {
        "meta": meta,
        "visited_urls": state.get("visited_urls", []),
        "findings": [f.model_dump() for f in state.get("findings", [])],
        "test_results": [r.model_dump() for r in state.get("test_results", [])],
    }
    (run / "report.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return run


# --- small rendering helpers (turn raw data into something a human can read) ---

def _short_field(selector: str) -> str:
    for pat in (r'\[name="([^"]+)"\]', r'\[data-testid="([^"]+)"\]', r'#([\w-]+)'):
        m = re.search(pat, selector)
        if m:
            return m.group(1)
    return selector if len(selector) <= 30 else selector[:27] + "…"


def _short_value(v: str) -> str:
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
    if not case.field_values:
        return "(nothing filled)"
    return ", ".join(
        f"{_short_field(s)}={_short_value(val)}" for s, val in case.field_values.items()
    )


def _server_note(result) -> str:
    statuses = []
    for f in result.findings:
        if f.category == "network_error":
            first = f.description.split()[0] if f.description else ""
            if first.isdigit():
                statuses.append(first)
    return f"server replied {', '.join(statuses)}" if statuses else ""


def _has_hard_evidence(result) -> bool:
    """True if the app itself complained (4xx/5xx or a script crash) — concrete proof
    something is off, independent of the robot's guess about what should happen."""
    return any(f.category in ("network_error", "js_error") for f in result.findings)


def _meta_block(meta: dict) -> list[str]:
    if not meta:
        return []
    rows = [
        ("Target", meta.get("target")),
        ("Provider / model", " / ".join(x for x in (meta.get("provider"), meta.get("model")) if x)),
        ("Locale", meta.get("locale")),
        ("Safety gate", "disabled (sandbox)" if meta.get("allow_all") else "enabled"),
        ("Duration", meta.get("duration")),
        ("Started", meta.get("started")),
    ]
    out = ["## Run", "", "| | |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in rows if v]
    out.append("")
    return out


def build_report(state, meta=None) -> str:
    meta = meta or {}
    findings = state.get("findings", [])
    visited = state.get("visited_urls", [])
    results = state.get("test_results", [])

    L: list[str] = []

    # ---- header: the one-line "what happened" ----
    sample_url = meta.get("target") or (visited[0] if visited else (results[0].url if results else ""))
    host = urlparse(sample_url).netloc or sample_url
    scored = [r for r in results if r.counts_toward_score]        # pass + review only
    passed = sum(1 for r in results if r.status == "pass")
    when = datetime.now().strftime("%d %b %Y")

    bits = [b for b in (host, f"{len(visited)} pages") if b]
    if scored:
        bits.append(f"{passed}/{len(scored)} checks behaved as expected")
    L.append("# QA Test Report")
    L.append(f"_{' · '.join(bits)} · {when}_")
    L.append("")
    L += _meta_block(meta)

    # ---- buckets by honest status ----
    review = [r for r in results if r.status == "review"]
    errored = [r for r in results if r.status == "error"]
    skipped = [r for r in results if r.status == "skipped"]
    info = [r for r in results if r.status == "info"]

    # ---- 1. flagged cases, split by how much we actually trust them ----
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
            if r.screenshot_path:
                L.append(f"   - Evidence: [screenshot]({r.screenshot_path})")
        L.append("")

    if maybe:
        L.append(f"## 🤔 Maybe — unmet guess, no error  ({len(maybe)})")
        L.append(
            "The form accepted (or rejected) something the robot only *guessed* about, "
            "and nothing actually errored. Usually a permissive form or an over-strict "
            "guess — skim these, don't trust them.\n"
        )
        for r in maybe:
            shot = f"  ([screenshot]({r.screenshot_path}))" if r.screenshot_path else ""
            L.append(
                f'- {r.url} — "{r.case.name}"  '
                f"(expected {r.case.expected}, got {r.observed}){shot}"
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
        _mark = {"pass": "✓", "review": "⚠", "info": "•", "error": "✗", "skipped": "–"}
        for url, page_results in by_url.items():
            page_scored = [r for r in page_results if r.counts_toward_score]
            page_passed = sum(1 for r in page_results if r.status == "pass")
            L.append(f"### {url} — {page_passed}/{len(page_scored)} ok")
            L.append("| Check | We typed | Should | Did | Status |")
            L.append("|---|---|---|---|---|")
            for r in page_results:
                typed = _typed(r.case).replace("|", "\\|")
                L.append(
                    f"| {r.case.name} | {typed} | {r.case.expected} "
                    f"| {r.observed} | {_mark.get(r.status, '?')} {r.status} |"
                )
            L.append("")

    # ---- 3. cases that never produced a verdict ----
    if errored:
        L.append(f"## Couldn't complete  ({len(errored)})")
        L.append("_Submit didn't fire, a fill failed, or the server errored (5xx)._\n")
        for r in errored:
            L.append(f'- {r.url} — "{r.case.name}" — {r.detail}')
        L.append("")

    if skipped:
        L.append(f"## Skipped  ({len(skipped)})")
        L.append("_Never ran — the site was unresponsive or a modal wouldn't open._\n")
        for r in skipped:
            L.append(f'- {r.url} — "{r.case.name}" — {r.detail}')
        L.append("")

    if info:
        L.append(f"## Informational — no oracle  ({len(info)})")
        L.append("_Ran, but the case had no known-correct answer to check against._\n")
        for r in info:
            L.append(f'- {r.url} — "{r.case.name}" (observed {r.observed})')
        L.append("")

    # ---- 4. app errors: crashes AND failed app requests ----
    app_errors = [f for f in findings if f.category in ("js_error", "network_error")]
    if app_errors:
        groups: dict = {}
        for f in app_errors:
            key = (f.severity, f.category, f.description, f.url)
            groups.setdefault(key, {"f": f, "n": 0})
            groups[key]["n"] += 1
        ordered = sorted(groups.values(), key=lambda g: _SEVERITY_ORDER.get(g["f"].severity, 99))
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
