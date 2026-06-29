from __future__ import annotations

import re
from playwright.async_api import Page, Error as PlaywrightError
from src.models.element import Element

class PageSnapshotter:
    """Turns a live Playwright page into a list of structured Elements."""
    # A trailing "-<suffix>" / "_<suffix>" that CONTAINS A DIGIT looks machine-
    # generated (e.g. "field-x7k2p", "mui-32") — unstable, so reject it. A suffix
    # that's a plain word does NOT (e.g. "...-PaymentMethod", "...-firstName") —
    # those are meaningful, stable ids we want to KEEP. The old pattern matched any
    # long suffix and wrongly discarded good MUI ids like the PaymentMethod select.
    _AUTOGEN_ID = re.compile(r'[_-][a-zA-Z0-9]*\d[a-zA-Z0-9]*$')
    _KINDKEYWORDS: dict[str, tuple[str, ...]] = {
            "password": ("password", "pwd", "pass"),
            "email":    ("email", "e-mail"),
            "phone":    ("phone", "tel", "mobile", "cell"),
            "date":     ("date", "dob", "birth", "birthday"),
            "address":  ("address", "street", "city", "state", "zip", "postal", "country"),
            "currency": ("price", "amount", "cost", "salary", "total", "payment"),
            "search":   ("search", "query"),
            "name":     ("name", "fname", "lname", "firstname", "lastname", "fullname"),
        }
    
    def __init__(self, page: Page) -> None:
        self._page = page

    async def extract_elements(self, root=None) -> list[Element]:
        # `root` (an ElementHandle) scopes extraction to a sub-tree — e.g. a modal
        # dialog — so we snapshot just the fields inside it, not the whole page.
        page = self._page
        results = []
        seen_radio_groups: set[str] = set()
        scope = root if root is not None else page
        handles = await scope.query_selector_all("input, button, a, select, textarea, "
                    "[role='button'][aria-haspopup='listbox'], "
                    "[role='combobox']"
                    )

        for handle in handles:
            # The page can mutate WHILE we snapshot it (a React re-render, a modal
            # closing) — so a handle grabbed a moment ago may already be detached
            # from the DOM. Any Playwright call on it then raises "Element is not
            # attached to the DOM". Catch that per-element and skip just that one,
            # instead of letting a single stale handle abort the whole snapshot.
            try:
                if await handle.get_attribute("aria-hidden") == "true":
                    continue
                tag = await handle.evaluate("el => el.tagName.toLowerCase()")
                element_type = await handle.get_attribute("type")
                role = await handle.get_attribute("role")
                aria_haspopup = await handle.get_attribute("aria-haspopup")
                widget_type = "mui_select" if (
                    aria_haspopup == "listbox" or role == "combobox"
                ) else "native"

                # Radios sharing a `name` are ONE logical field (pick one option), not N
                # separate fields. Emit the group once, with its options, and skip the rest.
                if tag == "input" and element_type == "radio":
                    radio_name = await handle.get_attribute("name")
                    if radio_name:
                        if radio_name in seen_radio_groups:
                            continue
                        seen_radio_groups.add(radio_name)
                        results.append(await self._build_radio_group(handle, radio_name))
                        continue

                options = await self._extract_options(handle, tag, widget_type)
                name = await self._resolve_name(handle, tag)
                selector = await self._pick_selector(handle, tag)
                required = await handle.get_attribute("required") is not None
                visible = await handle.is_visible()
                disabled = await handle.is_disabled()
                placeholder = await handle.get_attribute('placeholder')
                pattern = await handle.get_attribute("pattern")
                max_length_attr = await handle.get_attribute("maxlength")
                max_length = int(max_length_attr) if max_length_attr is not None else None
                kind = await self._infer_kind(handle, tag, element_type, name)
                in_form = await handle.evaluate("el => !!el.closest('form')")
                min_value = await handle.get_attribute("min")
                max_value = await handle.get_attribute("max")

                results.append(Element(
                    tag=tag,
                    element_type=element_type,
                    name=name,
                    selector=selector,
                    required=required,
                    visible=visible,
                    disabled=disabled,
                    semantic_kind=kind,
                    widget_type=widget_type,
                    in_form=in_form,
                    options=options,
                    placeholder=placeholder,
                    pattern=pattern,
                    max_length=max_length,
                    min_value=min_value,
                    max_value=max_value
                ))
            except PlaywrightError:
                # Stale/detached handle (the element vanished mid-snapshot) — skip
                # it and keep snapshotting the rest of the page.
                continue
        return results

    async def _build_radio_group(self, handle, radio_name: str) -> Element:
        # One Element for the whole group: name = the group's label (e.g. "Gender"),
        # options = each radio's visible label (e.g. ["Male", "Female"]). The executor
        # then picks ONE option, instead of the LLM guessing a value per radio.
        name = await self._resolve_name(handle, "input")
        safe = radio_name.replace("\\", "\\\\").replace('"', '\\"')
        options = await self._page.eval_on_selector_all(
            f'input[type="radio"][name="{safe}"]',
            """els => els.map(el => {
                const lbl = el.closest('label');
                const t = lbl ? (lbl.innerText || '').trim() : '';
                return t || el.value || '';
            }).filter(Boolean)""",
        )
        return Element(
            tag="input",
            element_type="radio",
            name=name,
            selector=f'input[name="{radio_name}"]',   # group base; not meant to be unique
            required=await handle.get_attribute("required") is not None,
            visible=await handle.is_visible(),
            disabled=await handle.is_disabled(),
            semantic_kind="unknown",
            widget_type="native",
            in_form=await handle.evaluate("el => !!el.closest('form')"),
            options=options or None,
        )

    async def _resolve_name(self, handle, tag:str) -> str:
        mui_label = await handle.evaluate("""el => {
            const fc = el.closest('.MuiFormControl-root');
            if (!fc) return null;
            const lbl = fc.querySelector('label, .MuiInputLabel-root');
            return lbl ? lbl.innerText.trim() : null;
        }""")
        if mui_label:
            return mui_label
          
        aria = await handle.get_attribute("aria-label")
        if aria and aria.strip():
            return aria.strip()
        
        labelled = await handle.evaluate("""el => {
                const ref = el.getAttribute('aria-labelledby');
                if (!ref) return null;
                const id = ref.split(/\\s+/)[0];
                const lbl = document.getElementById(id);
                return lbl ? lbl.innerText.trim() : null;               
            }""")
        if labelled:
            return labelled
        
        label_text = await handle.evaluate("""el => {
        if (el.id) {
            const lbl = document.querySelector(`label[for="${el.id}"]`);
            if (lbl) return lbl.innerText.trim();
        }
        const parent = el.closest('label');
        return parent ? parent.innerText.trim() : null;
        }""")
        if label_text:
            return label_text
        
        placeholder = await handle.get_attribute("placeholder")
        if placeholder and placeholder.strip():
            return placeholder.strip()
        
        if tag in ("button", "a"):
            text = (await handle.inner_text()).strip()
            if text:
                return text
        
        return "(unnamed)"
    
    async def _infer_kind(self, handle, tag: str, element_type: str | None, name: str) -> str:
        type_map = { # HTML type attribute
            "email": "email",
            "password": "password",
            "tel": "phone",
            "search": "search",
            "date": "date",
            "datetime-local": "date",
            "month": "date",
            "week": "date",
            "time": "date",
        }
        if tag in ("button", "a"):
            return "unknown"
        
        if tag == "input" and element_type in ("submit", "reset", "button", "checkbox", "radio", "hidden", "image", "file"):
            return "unknown"
        
        if element_type in type_map:
            return type_map[element_type]
        
        # Autocomplete
        autocomplete = await handle.get_attribute("autocomplete")
        if autocomplete:
            ac = autocomplete.lower()
            if ac == "email": return "email"
            if ac in ("tel", "tel-national", "tel-country-code", "tel-area-code", "tel-local", "tel-extension"):
                return "phone"
            if ac in ("name", "given-name", "family-name", "additional-name"):
                return "name"
            if ac in ("street-address", "address-line1", "address-line2", "address-line3", "postal-code", "country-name", "country-code"):
                return "address"
            
        # Keyword matching on name + id + placeholder.
        # Drop the "(unnamed)" sentinel — it literally contains "name" and
        # would otherwise false-match the name keyword.
        real_name = name if name != "(unnamed)" else ""
        el_id = await handle.get_attribute("id") or ""
        placeholder = await handle.get_attribute("placeholder") or ""
        haystack = " ".join([real_name, el_id, placeholder]).lower()

        for kind, keywords in self._KINDKEYWORDS.items():
            if any(kw in haystack for kw in keywords):
                return kind
        
        return "unknown"
    
    def _looks_autogenerated(self, el_id: str) -> bool:
        # React useId ids are unstable across renders. They show up as ":r5:" (colon
        # form, caught by the chars below) or "«r5»" (guillemet form) depending on
        # the React/MUI build — reject both so we fall through to a stable selector.
        if any(c in el_id for c in ":.[](){}#,«»"):
            return True
        return bool(self._AUTOGEN_ID.search(el_id))

    @staticmethod
    def _escape(text: str) -> str:
        # Escape backslashes first, then double quotes, so the text is safe
        # to drop inside a :text-is("...") selector.
        return text.replace("\\", "\\\\").replace('"', '\\"')

    async def _candidates(self, handle, tag: str) -> list[str]:
        out = []

        testid = await handle.get_attribute("data-testid")
        if testid:
            out.append(f'[data-testid="{testid}"]')

        el_id = await handle.get_attribute("id")
        if el_id and not self._looks_autogenerated(el_id):
            # A '#id' selector is ILLEGAL CSS if the id doesn't start with a
            # letter or underscore (e.g. '#357Fu' — an id beginning with a digit),
            # and query_selector_all throws a SyntaxError that aborts the run.
            # For those, use the always-valid attribute form '[id="..."]' instead.
            if re.match(r'^[A-Za-z_]', el_id):
                out.append(f'#{el_id}')
            else:
                out.append(f'[id="{self._escape(el_id)}"]')

        name_attr = await handle.get_attribute("name")
        if name_attr:
            out.append(f'{tag}[name="{name_attr}"]')

        # links get an href candidate
        if tag == "a":
            href = await handle.get_attribute("href")
            if href:
                out.append(f'a[href="{href}"]')

        # text-based candidate — only meaningful for links and buttons,
        # whitespace collapsed so multi-line text can't break the selector
        if tag in ("a", "button"):
            text = " ".join((await handle.inner_text()).split())
            if text and len(text) < 50:
                out.append(f'{tag}:text-is("{self._escape(text)}")')

        return out
        
    async def _pick_selector(self, handle, tag: str) -> str:
        # Try candidates strongest-first; return the first that matches
        # exactly one element on the page. Fall back to a positional path.
        for candidate in await self._candidates(handle, tag):
            if await self._is_unique(candidate):
                return candidate
        return await self._positional_selector(handle)

    async def _is_unique(self, selector: str) -> bool:
        matches = await self._page.query_selector_all(selector)
        return len(matches) == 1

    async def _positional_selector(self, handle) -> str:
        # Last resort: an nth-of-type path from the element up to <body>.
        # Guaranteed unique right now, but fragile if the page structure shifts.
        return await handle.evaluate("""el => {
            const parts = [];
            while (el && el.nodeType === 1 && el.tagName !== 'BODY') {
                let sel = el.tagName.toLowerCase();
                const parent = el.parentElement;
                if (parent) {
                    const sameTag = [...parent.children]
                        .filter(c => c.tagName === el.tagName);
                    if (sameTag.length > 1) {
                        const idx = sameTag.indexOf(el) + 1;
                        sel += `:nth-of-type(${idx})`;
                    }
                }
                parts.unshift(sel);
                el = parent;
            }
            return parts.join(' > ');
        }""")
    
    async def _extract_options(self, handle, tag: str, widget_type:str) -> list[str] | None:
        if tag == "select":
            return await handle.evaluate("""el =>
                Array.from(el.options)
                .map(o => (o.textContent || '').trim())
                .filter(Boolean)
            """)

        if widget_type == "mui_select":
            try:
                await handle.click(timeout=2000)
                await self._page.wait_for_selector(
                    "[role='listbox']", state="visible", timeout=2000
                )
                opts = await self._page.eval_on_selector_all(
                    "[role='option']",
                "els => els"
                ".filter(el => !(el.className || '').includes('MuiListSubheader-root'))"
                ".map(el => (el.innerText || '').trim()).filter(Boolean)"
                )
                await self._page.keyboard.press("Escape")    
                try:
                    await self._page.wait_for_selector(
                    "[role='listbox']", state="hidden", timeout=2000
                )
                except Exception:
                    pass

                try:
                    await self._page.locator(".MuiBackdrop-root").wait_for(
                    state="hidden", timeout=1000
                )
                except Exception:
                    pass
                return opts or None
            except Exception:
                return None
            
        return None
    
    


    
    