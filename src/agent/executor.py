from datetime import datetime
from playwright.async_api import Page
from src.models.element import Element
from src.models.action import ActionResult
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
        try:
            if element and element.widget_type == "mui_select":
                await self._mui_select(selector, value
                                       )
            elif element and element.tag == "select":
                await self._select(selector, value)

            elif element and element.tag == "input" and element.element_type in ("checkbox", "radio"):
                # any "truthy" value means: tick it
                if value.strip().lower() not in ("", "false", "no", "0", "unchecked"):
                    await self.page.check(selector, timeout=5000)

            elif element and (element.element_type == "date" or element.semantic_kind == "date"):
                # Native date inputs require ISO; a text date-picker takes the raw value.
                fill_value = _to_iso_date(value) if element.element_type == "date" else value
                await self.page.fill(selector, fill_value, timeout=5000)
                await self.page.keyboard.press("Escape")   # close any calendar overlay

            else:  # text / email / textarea / unknown
                await self.page.fill(selector, value, timeout=5000)

            return ActionResult(action="fill", selector=selector, value=value, ok=True)
        except Exception as e:
            return ActionResult(action="fill", selector=selector, value=value,
                                ok=False, detail=str(e)[:200])

    async def _select(self, selector: str, value: str) -> None:
        # try by visible label, then by value, then just pick the first real option
        for kwargs in ({"label": value}, {"value": value}, {"index": 1}):
            try:
                await self.page.select_option(selector, timeout=3000, **kwargs)
                return
            except Exception:
                continue
        raise Exception(f"no selectable option for {selector}")

    async def click(self, element: Element) -> ActionResult:
        verdict = await self.gate.evaluate(element)
        if verdict.risk == "destructive":
            return ActionResult(
                action="skip",
                selector=element.selector,
                ok=False,
                detail=f"blocked ({verdict.risk}): {verdict.reason}"
            )

        try:
            await self.page.click(element.selector, timeout=5000)
            await self.page.wait_for_load_state("networkidle", timeout=5000)
            return ActionResult(
                action="click",
                selector=element.selector,
                ok=True,
                detail=verdict.risk
            )
        except Exception as e:
            return ActionResult(
                action="click",
                selector=element.selector,
                ok=False,
                detail=str(e)[:200]
            )
        
    async def _mui_select(self, selector: str, value: str) -> None:
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
        v = value.strip().lower()
        for i, text, disabled in candidates:
            if disabled or not text or _is_placeholder(text):
                continue
            if v and text.strip().lower() == v:
                target_idx = i
                break

        # 2. Fallback: first real (non-placeholder, non-disabled) option
        if target_idx is None:
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


