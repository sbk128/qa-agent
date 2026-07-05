import re
from datetime import datetime

from playwright.async_api import Page

from src.models.action import ActionResult
from src.models.element import Element
from src.safety.gate import SafetyGate

_SUBMIT_WORDS = ("submit", "save", "continue", "sign up", "register", "next",
                 "apply", "search", "filter", "go")

# Native <input type="date"> only accepts an ISO YYYY-MM-DD value; anything else
# makes page.fill raise "Malformed value". Day-first formats are listed before
# month-first so an Indian-locale "15/07/2026" parses correctly.
_DATE_INPUT_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%Y", "%d-%m-%Y",
    "%m/%d/%Y", "%m-%d-%Y",
    "%d %B %Y", "%d %b %Y",
    "%B %d, %Y", "%b %d, %Y",
    "%B %d %Y", "%b %d %Y",
)


def _to_iso_date(value: str) -> str:
    """Convert a date string to ISO YYYY-MM-DD. If no known format matches,
    return it unchanged so the fill fails loudly (same as before the fix)."""
    v = value.strip()
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return v

_PLACEHOLDER_PREFIXES = ("select ", "choose ", "pick ", "all ", "any ", "-- ", "—")


def _is_placeholder(text: str) -> bool:
    t = text.strip().lower()
    return any(t.startswith(p) for p in _PLACEHOLDER_PREFIXES)


def _is_clickable(e) -> bool:
    if not e.visible or e.disabled:
        return False
    return e.tag == "button" or (e.tag == "input" and e.element_type in ("submit", "button"))


def _label_matches_submit(e) -> bool:
    return any(w in (e.name or "").lower() for w in _SUBMIT_WORDS)


def find_submit(elements):
    clickable = [e for e in elements if _is_clickable(e)]

    # 1. <button type="submit"> / <input type="submit"> inside a <form>
    for e in clickable:
        if e.in_form and e.element_type == "submit":
            return e

    # 2. In-form button whose label looks submit-y
    for e in clickable:
        if e.in_form and _label_matches_submit(e):
            return e

    # 3. Last button inside a form — submit buttons sit at the bottom
    in_form_buttons = [e for e in clickable if e.in_form]
    if in_form_buttons:
        return in_form_buttons[-1]

    # 4. Word-matched button anywhere on the page (handles non-form filter bars etc.)
    for e in clickable:
        if _label_matches_submit(e):
            return e

    # 5. Give up. We refuse to randomly click a header avatar.
    return None


class Executor:
    def __init__(self, page: Page, gate: SafetyGate) -> None:
        self.page = page
        self.gate = gate

    async def fill_form(self, values: dict[str, str], elements) -> list[ActionResult]:
        # map selector -> Element so we know each field's control type
        by_sel = {e.selector: e for e in elements}
        results = []
        for selector, value in values.items():
            results.append(await self._fill_one(by_sel.get(selector), selector, value))
        return results

    async def _fill_one(self, element, selector: str, value: str) -> ActionResult:
        # Can't type into a control that's disabled/readonly — skip it explicitly
        # (not a failure: happy-path readonly fields are pre-populated by the app).
        if element and (element.disabled or element.readonly):
            state = "disabled" if element.disabled else "readonly"
            return ActionResult(action="skip", selector=selector, value=value, ok=True,
                                detail=f"{state} field — not filled")
        try:
            fallback = False
            if element and element.widget_type == "mui_select":
                fallback = await self._mui_select(selector, value)
            elif element and element.tag == "select":
                fallback = await self._select(selector, value)

            elif element and element.element_type == "radio":
                # A radio group is one field: pick the one option matching `value`.
                fallback = await self._radio(selector, value)

            elif element and element.tag == "input" and element.element_type == "checkbox":
                # Truthy value -> tick it; falsy value -> untick it (both are testable states).
                truthy = value.strip().lower() not in ("", "false", "no", "0", "unchecked", "off")
                if truthy:
                    await self.page.check(selector, timeout=5000)
                else:
                    await self.page.uncheck(selector, timeout=5000)

            elif element and (element.element_type == "date" or element.semantic_kind == "date"):
                # Native date inputs require ISO; a text date-picker takes the raw value.
                fill_value = _to_iso_date(value) if element.element_type == "date" else value
                await self.page.fill(selector, fill_value, timeout=5000)
                await self.page.keyboard.press("Escape")   # close any calendar overlay

            else:  # text / email / textarea / unknown
                await self.page.fill(selector, value, timeout=5000)

            detail = "substituted a valid value (asked-for value not available)" if fallback else ""
            return ActionResult(action="fill", selector=selector, value=value,
                                ok=True, fallback=fallback, detail=detail)
        except Exception as e:
            return ActionResult(action="fill", selector=selector, value=value,
                                ok=False, detail=str(e)[:200])

    async def _select(self, selector: str, value: str) -> bool:
        # Try by visible label, then by value (exact intent). Returns fallback=False.
        for kwargs in ({"label": value}, {"value": value}):
            try:
                await self.page.select_option(selector, timeout=3000, **kwargs)
                return False
            except Exception:
                continue
        # Fallback: pick the first real option so the form is at least fillable, but
        # tell the caller we did NOT use the asked-for value.
        try:
            await self.page.select_option(selector, timeout=3000, index=1)
            return True
        except Exception as e:
            raise Exception(f"no selectable option for {selector}") from e

    async def _radio(self, group_selector: str, value: str) -> bool:
        # group_selector looks like input[name="gender"]; value is the chosen option label.
        # Returns True if we fell back to an arbitrary option instead of `value`.
        m = re.search(r'name="([^"]+)"', group_selector)
        name = m.group(1) if m else None
        v = value.strip().lower()
        if name:
            base = f'input[type="radio"][name="{name}"]'
            # 1. match by the radio's visible label text (most reliable)
            labels = self.page.locator(f"label:has({base})")
            for i in range(await labels.count()):
                lbl = labels.nth(i)
                if (await lbl.inner_text()).strip().lower() == v:
                    await lbl.click(timeout=5000)
                    return False
            # 2. match by the radio's value attribute
            try:
                await self.page.check(f'{base}[value="{value}"]', timeout=2500)
                return False
            except Exception:
                pass
            # 3. fallback: first option in the group (value not matched)
            try:
                await self.page.locator(base).first.check(timeout=2500)
                return True
            except Exception:
                pass
        # last resort: whatever selector we were handed
        await self.page.locator(group_selector).first.check(timeout=2500)
        return True

    async def click(self, element: Element) -> ActionResult:
        verdict = await self.gate.evaluate(element)
        if self.gate.should_block(verdict):
            return ActionResult(
                action="skip",
                selector=element.selector,
                ok=False,
                detail=f"blocked ({verdict.risk}): {verdict.reason}"
            )

        try:
            await self.page.click(element.selector, timeout=5000)
        except Exception as e:
            return ActionResult(
                action="click",
                selector=element.selector,
                ok=False,
                detail=str(e)[:200]
            )

        # Settling is best-effort: SPAs (e.g. a Vite dev server with an HMR socket)
        # often never reach "networkidle". A timeout here does NOT mean the click
        # failed, so don't let it fail the action — mirror session.goto's handling.
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        return ActionResult(
            action="click",
            selector=element.selector,
            ok=True,
            detail=verdict.risk
        )

    async def _mui_select(self, selector: str, value: str) -> bool:
        # Returns True if we fell back to an arbitrary option instead of `value`.
        # Click trigger to open the popup
        await self.page.click(selector, timeout=5000)
        # Wait for listbox to render
        await self.page.wait_for_selector(
            "[role='listbox']", state="visible", timeout=3000
        )
        # try to click option matching the value - case insensitive
        options = self.page.locator("[role='option']")
        count = await options.count()
        print(f"[mui_select] found {count} options")

        candidates = []
        for i in range(count):
            opt = options.nth(i)
            text = (await opt.inner_text()).strip()
            cls = (await opt.get_attribute("class")) or ""
            # MUI section headers carry role="option" but aren't selectable;
            # treat them like disabled rows so we never click one.
            is_subheader = "MuiListSubheader-root" in cls
            disabled = (await opt.get_attribute("aria-disabled")) == "true" or is_subheader
            candidates.append((i, text, disabled))

        print(f"[mui_select] candidates={candidates}")

        # 1. Exact, case-insensitive match against a non-placeholder option
        target_idx = None
        used_fallback = False
        v = value.strip().lower()
        for i, text, disabled in candidates:
            if disabled or not text or _is_placeholder(text):
                continue
            if v and text.strip().lower() == v:
                target_idx = i
                break

        # 2. Fallback: first real (non-placeholder, non-disabled) option
        if target_idx is None:
            used_fallback = True
            for i, text, disabled in candidates:
                if not disabled and text and not _is_placeholder(text):
                    target_idx = i
                    break

        if target_idx is None:
            raise Exception("no selectable option in MUI Select")
        
        chosen_text = candidates[target_idx][1]                               
        print(f"[mui_select] picking idx={target_idx} text={chosen_text!r}") 


        await options.nth(target_idx).click(timeout=3000)

        # 4. Wait for popup to close before next action
        await self.page.wait_for_selector("[role='listbox']", state="hidden", timeout=3000)
        # MUI keeps a transparent Backdrop alive during the close transition;
        # it eats subsequent clicks. Wait for it to actually disappear.
        try:
            await self.page.locator(".MuiBackdrop-root").wait_for(state="hidden", timeout=2000)
        except Exception:
            pass
        return used_fallback


