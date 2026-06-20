from playwright.async_api import Page, ConsoleMessage, Response
from src.models.finding import Finding

class Observer:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.console_errors: list[str] = []
        self.js_errors: list[str] = []
        self.network_errors: list[str] = []

        # Passive listeners - these fire on their own for the entire run.
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("response", self._on_response)

    def _on_console(self, msg: ConsoleMessage) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text)

    def _on_pageerror(self, exc) -> None:
        self.js_errors.append(str(exc))

    def _on_response(self, response: Response)-> None:
        if response.status >= 400:
            self.network_errors.append(f"{response.status} {response.url}")

    def collect_errors(self) -> list[Finding]:
        findings = []
        for text in self.js_errors:
            findings.append(Finding(
                severity="high", 
                category="js_error",
                title="Uncaught Javascript Error",
                description=text,
                url=self.page.url)
            )
        for status in self.network_errors:
            findings.append(Finding(
                severity="medium",
                category="network_error",
                title="Failed network request",
                description=status,
                url=self.page.url
            ))
        for text in self.console_errors:
            findings.append(Finding(
                severity="low",
                category="js_error",
                title="Console_error",
                description=text,
                url=self.page.url
            ))
        self.js_errors.clear()
        self.network_errors.clear()
        self.console_errors.clear()
        return findings
    
    # Active DOM check (Run after an action)
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
                url=self.page.url
            ))
        return findings
        