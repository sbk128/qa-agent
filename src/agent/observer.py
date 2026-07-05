from urllib.parse import urlparse

from playwright.async_api import ConsoleMessage, Page, Response

from src.models.finding import Finding


class Observer:
    def __init__(self, page: Page, app_host: str | None = None) -> None:
        self.page = page
        # When set, responses to other hosts (analytics, CDNs) are recorded as
        # low-severity third-party noise and are NOT used by the judge — only the
        # app's own responses decide accepted/rejected/error.
        self.app_host = (app_host or "").lower() or None
        self.console_errors: list[str] = []
        self.js_errors: list[str] = []
        # Structured network log: one dict per response {status, method, url}.
        self._responses: list[dict] = []

        # Passive listeners - these fire on their own for the entire run.
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("response", self._on_response)

    def _on_console(self, msg: ConsoleMessage) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text)

    def _on_pageerror(self, exc) -> None:
        self.js_errors.append(str(exc))

    def _on_response(self, response: Response) -> None:
        try:
            self._responses.append({
                "status": response.status,
                "method": response.request.method,
                "url": response.url,
            })
        except Exception:
            # A response can be gone by the time we read .request — ignore it.
            pass

    def _is_app_host(self, url: str) -> bool:
        if self.app_host is None:
            return True
        return urlparse(url).netloc.lower() == self.app_host

    # -- per-case scoping --------------------------------------------------- #
    def reset(self) -> None:
        """Drop everything buffered so far — call at the start of a fresh case."""
        self.js_errors.clear()
        self.console_errors.clear()
        self._responses.clear()

    def mark(self) -> int:
        """A cursor into the response log; pair with app_responses_since()."""
        return len(self._responses)

    def app_responses_since(self, mark: int) -> list[dict]:
        """App-host responses recorded after `mark` (i.e. since the submit click)."""
        return [r for r in self._responses[mark:] if self._is_app_host(r["url"])]

    def collect_errors(self) -> list[Finding]:
        findings = []
        for text in self.js_errors:
            findings.append(Finding(
                severity="high",
                category="js_error",
                title="Uncaught JavaScript error",
                description=text,
                url=self.page.url,
            ))
        for r in self._responses:
            if r["status"] < 400:
                continue
            same = self._is_app_host(r["url"])
            findings.append(Finding(
                # Third-party failures (analytics/CDN 4xx) are noise, not app bugs.
                severity="medium" if same else "low",
                category="network_error",
                title="Failed network request" if same else "Failed third-party request",
                description=f"{r['status']} {r['method']} {r['url']}",
                url=self.page.url,
            ))
        for text in self.console_errors:
            findings.append(Finding(
                severity="low",
                category="js_error",
                title="Console error",
                description=text,
                url=self.page.url,
            ))
        self.reset()
        return findings

    # Active DOM check (run after an action)
    async def check_page(self) -> list[Finding]:
        # Find every invalid input and, for each, resolve a human label and the
        # error message shown next to it. Returns a list of {field, message} dicts.
        invalid_fields = await self.page.evaluate("""() => {
            const inputs = document.querySelectorAll('[aria-invalid="true"], :invalid');
            const seen = new Set();
            const results = [];

            for (const el of inputs) {
                // :invalid can match a <form> too — keep only real fields
                const tag = el.tagName.toLowerCase();
                if (!['input', 'select', 'textarea'].includes(tag)) continue;

                // --- which field? resolve a human label, best source first ---
                let label = null;
                const fc = el.closest('.MuiFormControl-root');
                if (fc) {
                    const lbl = fc.querySelector('label, .MuiInputLabel-root');
                    if (lbl) label = lbl.innerText.trim();
                }
                if (!label) label = el.getAttribute('aria-label');
                if (!label && el.id) {
                    const forLbl = document.querySelector(`label[for="${el.id}"]`);
                    if (forLbl) label = forLbl.innerText.trim();
                }
                if (!label) label = el.getAttribute('placeholder');
                if (!label) label = el.getAttribute('name');
                if (!label) label = '(unknown field)';

                // --- why? read the error message near the field ---
                let message = '';
                const describedby = el.getAttribute('aria-describedby');
                if (describedby) {
                    message = describedby.split(/\\s+/)
                        .map(id => document.getElementById(id))
                        .filter(Boolean)
                        .map(n => n.innerText.trim())
                        .filter(Boolean)
                        .join(' ');
                }
                if (!message && fc) {
                    const help = fc.querySelector('.MuiFormHelperText-root');
                    if (help) message = help.innerText.trim();
                }
                if (!message && fc) {
                    const alert = fc.querySelector('.error, [role="alert"]');
                    if (alert) message = alert.innerText.trim();
                }

                // collapse duplicates (same label + message)
                const key = label + '||' + message;
                if (seen.has(key)) continue;
                seen.add(key);
                results.push({ field: label, message: message });
            }
            return results;
        }""")

        findings = []
        for item in invalid_fields:
            findings.append(Finding(
                severity="medium",
                category="validation",
                title=f"Invalid field: {item['field']}",
                description=item["message"] or "Field flagged invalid after action.",
                url=self.page.url,
            ))
        return findings
