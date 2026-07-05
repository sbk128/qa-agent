# QA Agent — Progress Checklist

Living checklist of build progress. `[x]` done, `[ ]` todo, ← current focus.
See [`qa_agent_plan_v2.md`](../qa_agent_plan_v2.md) for the original plan.

## Where you are right now
**The pipeline now runs end-to-end on TWO LLM backends: Groq (cloud) and a local Ollama model
(`gemma4:e4b`) — verified by a clean 22-case run on the demoqa practice form (2026-06-29, 11/22,
report written). Test Engine Step 4 is DONE (per-case report table + engine runs on every crawled
page).**
**Next: saved suites — cache the per-form suite and let a human edit `expected` once (that's the
missing oracle). One fix closes gap #1(a) AND gap #3 (runs become comparable/regression-able).**

The original 6-phase plan is done. On top of it, a 4-step "test engine" (LLM-generated test
cases → execute → judge pass/fail). All four steps are built and verified on live forms.

### → Do this next (reassessed 2026-07-03)
1. **Saved suites — one fix for gaps #1(a) + #3.** Cache the generated suite per form (JSON keyed by
   URL), reuse it on later runs, and let a human edit `expected` once — that edit IS the missing
   oracle. Runs become comparable (regression detection), and Ollama re-runs skip the slow plan step.
2. **Dashboard / read-only mode.** Pages with no submit get zero coverage today (`plan_node` skips
   them). Scope: click filters, assert content reacts, no console/network errors, flag empty states.
3. **Judge scoping.** Attribute 4xx/5xx to the actual submit request (drop favicon/analytics noise);
   distinguish 404 (route error) from 400/409/422 (validation reject).
4. **Coverage leftovers.** Icon-only `+` FAB launchers (match aria-label/testid), multi-step wizard
   walking, button-nav auto-discovery (routes seed works but is manual).
5. **Agent self-tests.** `tests/` is empty; `_judge`, `build_edge_cases`, `find_submit`, the gate's
   rules layer are pure-ish and cheap to cover. Two providers + multi-device now — regressions are
   otherwise invisible.
- Micro-cleanup: `agent_graph.py` has a redundant `observe → END` edge alongside `observe → decide`
  (decide's conditional edge is what actually routes to END). Harmless, confusing.

### Worklog
- **Session 2026-06-29 — local LLM (Ollama) + Windows fixes + flaky-site resilience.** Verified by a
  clean end-to-end run on the demoqa practice form using the local model (22 cases, 11/22, report OK).
  - **`OllamaProvider` (`src/llm/ollama_provider.py`, NEW).** Mirrors GroqProvider (text / structured /
    retry-backoff) against a local `ollama serve` via `/api/chat`; default model `gemma4:e4b`
    (override via `OLLAMA_MODEL` / `OLLAMA_BASE_URL`). `structured()` passes the Pydantic JSON schema
    as Ollama's `format` (constrained decoding — much better JSON from small models), falling back to
    plain JSON mode if the schema is rejected. Registered in `get_provider(name)` — explicit arg wins,
    else `LLM_PROVIDER` env. The `model` kwarg is accepted-but-ignored (one local model; callers
    passing Groq slugs like SMALL_MODEL must not break).
  - **Truncation fix (the "plan ok: 0 cases" bug).** Ollama's default ~4k context silently truncated
    the test-suite JSON mid-string (`EOF while parsing`). Now `num_ctx=16384`, `num_predict=-1`
    (env-overridable). The model reasoned fine — it just ran out of room.
  - **GUI: LLM provider dropdown (`main_window.py`, `workers.py`).** Groq (cloud) / Ollama (local) per
    run → `RunConfig.provider` → `get_provider(cfg.provider)`. The Groq-key check only applies when
    Groq is selected; the header chip tracks the choice. NOTE for Ollama runs: keep Sandbox/allow-all
    ON — the safety gate otherwise fires a per-click LLM call, which is painfully slow locally.
  - **UTF-8 report fix (Windows).** `write_text` defaulted to cp1252 → `UnicodeEncodeError` on ⚠/✓ —
    the whole run died at report time. All report writes/reads now pass `encoding="utf-8"`
    (`report.py`, `report_loader.py`, `main_window.py`). Pre-existing; would have crashed on Groq too.
  - **Circuit breaker (`runner.py`).** demoqa went unresponsive mid-run and every remaining case
    burned the full 120s hang budget (~28 min of dead grind). Now after `_CONSECUTIVE_FAIL_LIMIT=2`
    navigation failures/hangs in a row, the rest of the page's cases are recorded as skipped `error`s.
    A judged `error` on a healthy page load resets the counter (only site-level failures count).
  - **Edge-case cap `_MAX_PER_FIELD` 6 → 2 (`testgen.py`).** demoqa form: 45 → 22 cases. Faster runs,
    gentler on flaky public targets, still per-field coverage.
- **Session 2026-06-27/28 — trustworthiness + robustness + coverage.** A run of fixes, all verified
  by re-running on the live app:
  - **Report fully redesigned (`reporting/report.py`).** Leads with what to act on, shows the actual
    data typed per case, drops the "Actions taken: 0" noise, demotes the URL dump. Flagged cases are
    split by *confidence*: **"⚠ Worth checking"** (the app gave hard evidence — a 4xx/5xx or JS crash,
    via `_has_hard_evidence`) vs **"🤔 Maybe"** (form just didn't match the LLM's guess, no error). This
    stops the report crying wolf — e.g. demoqa's permissive forms land in "maybe", real `422`/`404`s
    rise to "worth checking". GUI unaffected (reads `report.json`, which is unchanged).
  - **Dropdown mis-fill FIXED — the big one (`snapshotter.py`).** MUI Selects were getting fragile
    positional selectors (`div > div > div…`) → mis-fills → false rejects (even happy paths). Root
    cause: `_AUTOGEN_ID` discarded *good* stable ids like `mui-component-select-PaymentMethod` because
    the regex matched any `[-_]<5+ alnum>$` suffix. Now it only rejects suffixes that **contain a
    digit** (hashes/counters), keeping meaningful word-suffix ids. Verified live: report now shows
    `mui-component-select-Gender="Male"` etc., readable + stable. Diagnosed via new
    `scripts/inspect_dropdowns.py`.
  - **Two snapshot crash fixes (`snapshotter.py`).** (a) `#357Fu`-style ids (id starting with a digit)
    made an invalid CSS selector → use the `[id="…"]` attribute form for non-letter-start ids.
    (b) Elements detaching mid-snapshot (a modal's Close button) raised "not attached to DOM" → per-
    element `try/except PlaywrightError: continue` so one stale handle can't abort the whole snapshot.
  - **Hang guard + progress logging.** A run froze silently inside one test case. Added (1) breadcrumb
    logging at every graph node (`agent_graph.py` `_log`) + per-case + fill/submit (`runner.py`) so a
    hang now NAMES where it is; (2) a hard **120s per-case budget** (`asyncio.wait_for` in `run_suite`)
    → a stuck fill/submit is recorded as `error` and the run continues instead of hanging forever.
    Localised via new `scripts/time_snapshot.py`. NOTE: the original hang was non-deterministic and
    didn't reproduce — root cause still unknown, but it's now self-healing + will be logged if it recurs.
  - **Multi-page coverage via routes seed (GUI).** This SPA navigates by buttons, so the link crawler
    only ever reached the seed page. New "Also test these pages" box (`main_window.py`) → `RunConfig.routes`
    → seeds `frontier` in `workers.py`. Each listed URL is visited + tested (capped by Max pages).
    Addresses gap #2 pragmatically (no fragile button-crawling).
  - **Sandbox `--allow-all` now ON by default in the GUI** (`main_window.py` `setChecked(True)`) — the
    usual target is a throwaway dev box; untick before pointing at real data.
  - **Viewport fixed for the 13" M2 Air** (`session.py`): `--window-side` typo → `--window-size`;
    viewport 1440×860 → 1280×740 + pinned top-left, so the headed window stops spilling off-screen.
- **Network-aware judge — BUILT + VERIFIED (2026-06-26).** `_judge` (`runner.py`) now reads the
  Observer's 4xx/5xx `network_error` findings (new `_network_statuses` helper), not just client-side
  validation: 4xx → `rejected`, 5xx → `error`. Closes gap #1(c) — backend rejections were masked as a
  false `accepted`. Verified by replaying the `run-20260626-175548` findings through the new judge: 3
  false-`accepted` cases (a real `422` on /transactions, two `404`s on /cash-in/opd) flip to correct
  `rejected` → 22/44 → **25/44**, no regressions, no happy-path broken. ROUGH EDGE (logged, not fixed):
  all 4xx treated alike, but a `404` is route-not-found (arguably `error`) vs `400/409/422` = validation
  reject; and it still counts unrelated 4xx noise (favicon/analytics) — later, scope to the submit request.
- **Modal-triggered forms — BUILT (2026-06-26), pending end-to-end test.** `src/agent/modal_tester.py`
  (`ModalTester`), wired into `execute_node` so it runs on every crawled page. Discovers launchers by
  verb-prefix (`Add/New/Create/Edit`) across tabs → opens each → snapshots scoped to the
  `[role="dialog"]` (via `extract_elements(root=...)`) → generates + runs a suite (reload, re-open,
  fill inside the dialog, submit, observe, judge) → closes (Cancel/Escape). Results tagged `url#Label`
  so the report groups one section per modal. Safety gate updated: create verbs (`Add/Save/…`) are
  safe, so `Add Payment` isn't blocked by the `"pay"` rule (destructive verbs still blocked).
  Mechanism proven via probe on IPD Billing (modal opened, 5 fields extracted, submit `ADD PAYMENT`).
  KNOWN GAPS: icon-only launchers (FAB `+` has no text) aren't detected; `ADD CHARGE` (inline row,
  not a dialog) is correctly skipped. **Run a full crawl on the accounting module to verify.**
- **Sandbox `--allow-all` flag (2026-06-26).** The accounting cash-in forms submit via `SUBMIT
  TRANSACTION`, which the safety gate's LLM (correctly) flags destructive → click skipped → all cases
  `error` (this caused the 4/31 run). New opt-in `--allow-all` (CLI) / "Sandbox" checkbox (GUI) sets
  `SafetyGate(allow_all=True)` → gate returns `safe` for everything. Off by default; for dev/test
  targets only. Threads gate → `build_agent_graph` → show_agent/`RunConfig`.
- **VERIFIED end-to-end on the accounting module (2026-06-26, with `--allow-all`).** Modal tester
  found + tested both payment modals (`…#ADD PATIENT PAYMENT`, `…#ADD PROFESSIONAL PAYMENT`) — happy
  paths `accepted`, required-field rejections caught. With the sandbox flag on, the cash-in *page*
  forms (`opd`, `general`) flipped from all-`error` to real results. Overall 22/44; `review` rows =
  real under-validation candidates (forms accept overlong / special-char / invalid input).
- KNOWN REMAINING: bare `/cash-in/ipd_bill` (no `?ipdnumber=`) is all-`error` — a lookup form with no
  patient loaded (submitting navigates/fails), not a gate block. Degenerate page; the real flow is the
  param'd page + its modals. Icon-only `+` FAB launchers still undetected (no text).
- **Dashboard / read-only verification (planned, after modals).** Pages like the Financial Dashboard
  and Transactions list have nothing to fill+submit — testing them is a different *mode*: click filters
  (Last 7/30/90 days, date range, Apply) and assert the data changes + no console/network errors +
  flag empty states (`No Data Available`, `₹0`). Correctness of the numbers needs an oracle the agent
  doesn't have, so scope = "loads, reacts, doesn't error," not value-checking.
- **Step 4 — Report + crawl integration — DONE.** Per-case pass/fail table = "Results by form" in
  `report.py` (2026-06-27 redesign); the engine already runs on every crawled page (`plan_node` →
  `execute_node` each lap, + modal scan). Verified on a 2-page demoqa crawl (2026-06-29).
- **Note on the `review` mismatches.** Edge cases that expect `rejected` often show `accepted` (the form
  under-validates, or the LLM's `expected` was too strict). Framed as *review*, not bugs.

---

## What's lacking — honest gaps (assessed 2026-06-26, for next session)
Ordered by impact. The engine *drives* real apps well now; the weaknesses are mostly about
**trustworthiness of results** and **coverage**, not basic mechanics.

1. **Findings aren't trustworthy yet — biggest gap.** A `review` row ("expected rejected, observed
   accepted") can't distinguish a real bug from noise, because: (a) **no oracle** — `expected` is the
   LLM's guess, not a spec; (b) **shallow edge data** — the LLM doesn't reliably emit *genuinely*
   invalid values, and `_mui_select`/radio fills auto-repair bad dropdown choices, so the "bad" input
   often isn't bad by submit time; (c) ~~**client-side only**~~ **DONE (2026-06-26)** — `_judge` now also
   reads the Observer's 4xx/5xx network findings, so a backend rejection is no longer masked as a false
   `accepted` (see worklog up top). ~~(b)~~ **DONE** — `build_edge_cases` (`testgen.py`) injects real
   nasties from the static lib one-field-at-a-time onto the LLM's happy-path baseline (capped
   `_MAX_PER_FIELD=2`). → Remaining: **(a) no-oracle** → saved suites (see Do this next).
2. **Coverage is shallow** (partly addressed 2026-06-28). The crawler still only follows `<a href>`,
   but the **routes seed** (GUI "Also test these pages" → `RunConfig.routes` → `frontier`) now lets you
   hand it the pages this button-driven SPA hides, so multi-page testing works. Still open: button/
   `[role=link]` auto-nav discovery, multi-step **wizard** walking (patreg = step 1 only), **dashboards
   / read-only** assertion mode, icon-only `+` FAB launchers.
3. **No determinism / regression-ability.** Every run regenerates cases via the LLM, so case counts and
   pass rates wobble; you can't compare runs or catch regressions. → Optional: cache/seed a suite per
   form (a "saved suite" mode).
4. ~~**Report & UX leftovers (Step 4).**~~ **DONE 2026-06-27** — report redesigned: shows the data
   typed per case, drops the always-0 "Actions taken" line, splits flagged cases by confidence
   (Worth checking vs Maybe). Still open: no HTML report; finding descriptions still sometimes fall
   back to the generic string.
5. **Operational.** Slow + token-heavy (reload-per-case, modal re-open-per-case); creates real records
   with no cleanup (fine on dev DB, but it accumulates); positional selectors still used for radios /
   some buttons (fragile); the agent itself has ~no automated tests.

### ✅ Just finished — the data-quality thread (verified 2026-06-19 on /opd/bookappointment)
- **(A) LLM-blind text fields — DONE.** Snapshotter captures `placeholder` / `pattern` / `max_length`
  / `min_value` / `max_value` onto `Element`; `country_hint` resolves via a 3-layer fallback
  (seeded `--locale` → LLM inference → `DEFAULT_COUNTRY`).
- **(B) Findings name the field — DONE.** `Observer.check_page()` walks each invalid input, resolves a
  human label + reads the adjacent error text, emits one `Finding` per field. Verified: now reads
  `Invalid field: Time Slot — Time slot is required` instead of `2 field(s) flagged invalid`.
- **Native date fill — DONE.** `executor._to_iso_date` normalizes any date format to ISO `YYYY-MM-DD`
  before filling a native `<input type="date">` (which otherwise raises "Malformed value").
- **Generator parity (the real root cause) — DONE.** The test engine runs `TestCaseGenerator`, NOT the
  `DataGenerator` we'd enriched — so the constraint work wasn't reaching the tests. Extracted one shared
  `describe_fields()` helper (in `generator.py`) that BOTH generators call, and added the constraint /
  options / ISO-date+min/max instructions to `TestCaseGenerator`'s prompt. The two can't drift again.
- **MUI subheader filter — DONE.** `MuiListSubheader-root` rows carry `role="option"` but aren't
  selectable. `_extract_options` (snapshotter) now drops them so the LLM never picks one, and
  `_mui_select` (executor) treats them as disabled. This fixed the submit-click `error`s (picking a
  header left the dropdown open, and its backdrop blocked the submit button).
- **Result:** happy path fills a future date + real dropdown values (e.g. Time Slot `09:00 - 09:30 AM`)
  and is `accepted`. No more `error` outcomes.

### ✅ Also done — authenticated crawling + crash-resilience (2026-06-24)
Target moved to the in-dev app at `http://192.168.0.191:8000` (behind a JWT login). It's a dev/test
copy, so form submits creating real records is fine — no `--no-submit` needed.
- **Auth capture — `scripts/login.py` (NEW).** Opens a headed browser at the login page and waits for
  YOU to log in by hand (auto-detects leaving `/login`; Enter is a fallback). Saves the session
  (cookies + localStorage, incl. the JWT) to `auth.json` via Playwright `storage_state`, and prints a
  cookie/origin sanity count so an empty capture is obvious. Login is deliberately a SEPARATE script so
  the test agent never fills/submits the login form itself.
- **Session reuse.** `BrowserSession(storage_state=...)` starts the context already authenticated.
  `show_agent.py` auto-loads `auth.json` when it holds a real session (`_has_session` guards against the
  empty-file trap that silently skipped login before). `auth.json` is git-ignored (live token).
- **Runner crash-resilience.** `TestRunner._reload` retries the per-case page reload (2× at 60s); if it
  still fails, that case is recorded as an `error` TestResult instead of the `net::ERR_TIMED_OUT`
  exception aborting the whole suite. `session.goto` now takes an optional `timeout`.
- **Note:** the safety gate allows form *submits* by design (only blocks destructive verbs like
  delete/pay). Fine here since it's a dev DB; revisit if ever pointed at live data.

### Reference docs (written for catching up)
- `docs/QA_Agent_Walkthrough.pdf` — what each stage does, traced through the waitlist example.
- `docs/QA_Agent_Code_DeepDive.pdf` — how the code works (async/await, handles vs locators, the
  JS bridge, Pydantic, the LLM call). Source HTML + `scripts/html_to_pdf.py` alongside.

---

## Phase 0 — Setup ✅
- [x] Repo scaffold, `pyproject.toml`, uv env
- [x] LLM provider abstraction + `GroqProvider` (retry, JSON mode, backoff)
- [x] `OllamaProvider` — local LLM via Ollama `/api/chat`, schema-constrained `structured()`,
      `num_ctx=16384`; selectable via `get_provider(name)` / `LLM_PROVIDER` / GUI dropdown (2026-06-29)
- [x] `BrowserSession` (open / screenshot / summary)
- [x] Single-node LangGraph + `main.py` CLI

## Phase 1 — Page Understanding ✅ (core)
- [x] `Element` Pydantic model
- [x] Element extraction (input / button / a / select / textarea)
- [x] Accessible name resolver (aria-label → `<label>` → placeholder → text)
- [x] Selector picking with uniqueness check + positional fallback
- [x] `visible` / `disabled` detection
- [x] `semantic_kind` — Layer 1 `type` → Layer 2 `autocomplete` → Layer 3 keywords → `unknown`
- [x] `InferredContext` (one LLM call → language / country / currency / domain / app_type)
- [x] `PageSnapshotter` refactor (snapshot logic out of `session.py`)
- [x] Tested on 5+ varied sites

Added during real-app hardening:
- [x] `widget_type` (`native` / `mui_select`) — detects MUI Selects via `role="combobox"` / `aria-haspopup="listbox"`
- [x] `in_form` flag (`el.closest('form')`) — powers `find_submit` priority
- [x] `options` — real dropdown choices, read by `_extract_options` (native `<select>` directly; MUI Select by opening the popup)
- [x] MUI label fix — `.MuiFormControl-root` walk-up so name = field label, not current value
- [x] `_looks_autogenerated` rejects React `useId` ids (`:r5l:` etc.)

Constraint capture (was weak-spot A — now DONE):
- [x] **Capture input constraints (`pattern`, `maxlength`, `min`/`max`, `placeholder`) → `Element`.** Read in `extract_elements`; fed to both generators via the shared `describe_fields()` helper. Fixed US-phone junk and the past-date / min-violation on the OPD date field.
- [ ] Naming fixes: submit-button `value`, `<select>` labels, id-derived names
- [ ] Compression strategy (keep snapshot under ~5k tokens)
- [ ] Shadow DOM / iframes

## Phase 2 — Safety Gate ✅ (core)
- [x] `SafetyVerdict` model + DESTRUCTIVE / AMBIGUOUS pattern lists
- [x] Layered classifier: rules → ambiguous keywords → small-LLM judge → default safe
- [x] Validated on isolation tests + live pages

Deferred:
- [ ] DOM-signal layer (read `title`, `data-confirm`, surrounding warning text — fixes icon-only delete blind spot)
- [ ] Domain allowlist enforcement
- [ ] Policy enforcement (block / confirm / allow integration)

## Phase 3 — Data Generation ✅ (core)
- [x] `FormFill` model
- [x] `DataGenerator.happy_path` — one LLM call per form, locale-aware
- [x] `edge_cases()` static library (`UNIVERSAL` + `KIND_SPECIFIC` by `semantic_kind`)
- [x] `fillable()` helper — now widened to include selects + checkboxes + radios

## Phase 4 — Core Agent Loop ✅
- [x] `ActionResult` model
- [x] `Executor` — `fill_form` + safety-gated `click`
- [x] `find_submit` helper — priority ladder: `type=submit` in form → label-match in form → last in-form button → label-match anywhere → give up (never clicks a stray header button)
- [x] `Observer` — passive listeners (console / pageerror / 4xx-5xx network) + active DOM check (validation)
- [x] `Finding` model + buffer-drain fix
- [x] `AgentState`
- [x] LangGraph wiring: `snapshot → infer_context → plan → execute → observe → END`

## Phase 5 — Autonomous Navigation ✅ (core)
- [x] **Sub-step 1:** `decide` node + conditional loopback edge + reducers (`operator.add`) so findings/actions accumulate + `max_iterations` cap + `visited_urls` tracking
- [x] **Sub-step 2:** Global **frontier** — cross-page memory of unvisited links; agent now explores beyond dead-ends

Deferred:
- [ ] Sub-step 3: State hashing (same-page-different-URL dedup, e.g. `#fragments`)
- [ ] Sub-step 4: Dead-end recovery (close modals, escape stuck pages)
- [ ] Sub-step 5: Prioritization (which link first) + smarter limits

## Phase 6 — Reporting ✅ (core)
- [x] `build_report` (Markdown) + `write_report` (Markdown + JSON to timestamped `reports/run-*/`)
- [x] Dedup (collapse identical findings, count `×N`)
- [x] Severity sorting (critical → info)
- [x] Coverage map (visited URLs)

Deferred:
- [ ] Scope filtering (drop third-party / out-of-scope noise like doubleclick)
- [ ] HTML report (Jinja2)

---

## Test Engine (the LLM-driven test-case sub-system)

The "LLM generates test cases, runs them, judges pass/fail" build on top of the 6 phases.

- [x] **Step 1 — TestCase model + Generator** → `src/models/testcase.py`, `src/agent/testgen.py`, `scripts/show_testcases.py`
      - LLM produces a suite of cases (happy / edge / scenario), each with data + expected outcome + rationale.
      - Verified on demoqa practice form: generated 10 diverse cases.
- [x] **Step 2 — Widget-aware Executor** → `src/agent/executor.py` (`_fill_one` dispatcher + `_select` + `_mui_select`)
      - Dispatches by control type: MUI Select → `_mui_select`, `<select>` → `select_option`, checkbox/radio → `check`, date → `fill + Escape`, else → `fill`.
      - `_mui_select`: open popup → skip placeholders → exact-match option → click → wait for listbox + `.MuiBackdrop-root` to clear.
      - Verified on practice form (invalid fields 5 → 2) and on the hospital MUI dropdowns.
- [x] **Step 3 — Runner + Judge** → `src/agent/runner.py` (`TestRunner.run_one` / `run_suite` / `_judge`)
      - Per case: reload form → fill data → click submit → observe → `_judge` maps to `error` / `rejected` / `accepted` → compare vs `expected` → `passed`.
      - Mismatches framed as review findings, not definitive bugs.
      - **Verified end-to-end 2026-06-19** via `scripts/show_agent.py` on /opd/bookappointment: happy
        path `accepted`, edge mismatches surfaced as `review`. (Runs inside the graph's execute node;
        no separate `show_run.py` demo needed.)
- [x] **Step 4 — Report + crawl integration** — DONE
      - Per-case pass/fail table = "Results by form" in `build_report` (`report.py`, 2026-06-27
        redesign), incl. the data typed per case.
      - Engine runs on every crawled page: `plan_node` → `execute_node` each lap, plus the
        `ModalTester` scan. Verified on a demoqa 2-page crawl (2026-06-29).

---

## Real-app hardening (the last multi-day effort) ✅
Made the Phase 4 pipeline actually drive a real Material UI SPA — the hospital management app
(`localhost:5173`, OPD filter page + waitlist form). Verified working end-to-end.
- [x] Detect MUI Selects (`role="combobox"` / `aria-haspopup="listbox"`) — they are `<div>`s, not `<select>`
- [x] `_extract_options` reads real dropdown choices into `Element.options`
- [x] Feed `options` to `DataGenerator` so the LLM picks real values (no more hallucinated "Dr. Rachel Kim")
- [x] `_mui_select` dropdown dance + placeholder skip + backdrop wait (fixed "Apply Filters didn't fire")
- [x] `find_submit` + `in_form` (fixed clicking the header avatar instead of "Add to Waiting List")
- [x] MUI label resolution + React `useId` selector handling + 1440×860 viewport for the M2 Air

### Two weak spots — both now CLOSED (verified 2026-06-19)
- [x] **(A) LLM-blind text fields.** Captured constraints + min/max into `Element`; shared `describe_fields()` feeds both generators; `country_hint` resolves via 3-layer fallback. Plus: native-date ISO normalizer + MUI subheader filter (surfaced while verifying). Happy path now `accepted`.
- [x] **(B) Findings don't name the field.** `check_page()` now names each invalid field and reads its error text (e.g. `Invalid field: Time Slot — Time slot is required`).

### Known limitations of the test engine
- Custom JS widgets (react-select-style) — `fill` is best-effort, may not commit
- LLM can't emit huge literals (`'a".repeat(1000)'` artifact) — inject from `edge_cases()` static lib
- `expected` is the LLM's guess, not a spec — Judge must frame mismatches as "review," not "BUG"
- App-specific validation rules (demoqa 10-digit phone) — capture HTML constraints (deferred Phase 1)
- Multi-step journey testing (Tier 3) — likely needs human-seeded journey templates; not autonomous
- **Big forms can exceed the LLM JSON limit.** Many fields × long positional selectors bloat the
  test-suite JSON → Groq `json_validate_failed`. Now crash-safe: `plan_node` catches it and skips the
  page (2026-06-24). Real fix = shorter selectors (see useId fix below) to shrink the payload.
- **Multi-step wizards (e.g. `/ipd/patreg`).** "Next" is disabled until the form is valid; the agent
  tests one page, doesn't walk the wizard. If fills fail, every case reports `error`.

### Surfaced + fixed via `/ipd/patreg` (2026-06-24)
- **`plan_node` resilience** — a failed `testgen.generate` (transient Groq error / oversized JSON) is
  caught and the page is skipped, instead of `RuntimeError` aborting the whole crawl.
- **React `useId` selectors (`«r5»`)** — `_looks_autogenerated` now rejects the guillemet `«…»` useId
  format (it already caught the `:r5:` colon format). Fields fall through to their stable `name`
  attribute (`input[name="firstName"]`) instead of an unstable per-render id — fixing fills-fail-on-reload
  and shrinking the LLM payload.
- **`networkidle` was a false success-gate in `executor.click`** — the click succeeded but the follow-up
  `wait_for_load_state("networkidle")` timed out (Vite HMR socket never goes idle), which marked the
  whole click failed → every case `error`. Now the click and the settle-wait are separate: a click
  failure → `error`, but a networkidle timeout is best-effort (ignored), mirroring `session.goto`.
- **Result:** `/ipd/patreg` went 0/8 (all `error`) → **2/5**: happy path `accepted`, empty-required
  correctly `rejected`, 3 `review` (accepts invalid phone / overlong / special chars).

---

## Desktop GUI (`gui/`) — added 2026-06-25
A PySide6 (Qt) front-end over the same agent — no behaviour change, it just surfaces it.
Run with `uv sync --group gui` then `uv run qa-agent-gui`.
- Reuses `build_agent_graph` / `BrowserSession` / `write_report` directly, so every fix here
  (auth, networkidle, useId selectors, plan_node resilience) applies automatically.
- `RunWorker`/`LoginWorker` drive the async agent on a background QThread (private asyncio loop),
  streaming node-by-node progress to the UI via Qt signals; `astream(stream_mode="updates")`.
- Config form (url/locale/auth/headless/max-pages), live findings + test-results + coverage,
  log console, History panel (re-renders past `reports/run-*`), Settings (writes `.env.local`).
- **LLM provider dropdown (2026-06-29):** Groq (cloud) or Ollama (local `gemma4:e4b`) per run;
  Groq-key check only enforced for Groq.
- See `gui/README.md`. Note: "Max pages" overrides `agent_graph.MAX_ITERATIONS` per run.

## Scripts at a glance
| Script | What it demonstrates |
|---|---|
| `scripts/show_elements.py` | Phase 1 — element extraction + selectors + `semantic_kind` |
| `scripts/show_context.py`  | Phase 1 — page-level `InferredContext` via LLM |
| `scripts/show_safety.py`   | Phase 2 — safety gate (fakes mode + `--url` live mode) |
| `scripts/show_data.py`     | Phase 3 — happy-path data generation + edge-case list |
| `scripts/show_execute.py`  | Phase 4 — full pipeline on one page (fill + submit + observe), headed |
| `scripts/show_agent.py`    | Phases 5–6 — autonomous multi-page crawl, writes a report (reuses `auth.json` if present) |
| `scripts/show_testcases.py`| Test engine step 1 — LLM-generated test suite (prints, no execution yet) |
| `scripts/login.py`         | Capture an authenticated session → `auth.json` (manual login, no test agent involved) |