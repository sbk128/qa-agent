from src.data.edge_cases import KIND_SPECIFIC, UNIVERSAL
from src.llm import LLMProvider
from src.models.context import InferredContext
from src.models.data import FormFill
from src.models.element import Element


class DataGenerator:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def happy_path(self, elements: list[Element], context: InferredContext) -> dict[str, str]:
        fields = fillable(elements)
        if not fields:
            return {}
        field_lines = describe_fields(fields)
        prompt = (
            "You are a helpful assistant that generates realistic test data for filling out web forms. "
            "Given the following form fields, their semantic kinds, and the overall page context, "
            "generate appropriate values for each field. Use the semantic kind and label to guide your choices. "
            "For example, for an email field, generate a realistic email address; for a name field, generate a plausible name. "
            "IMPORTANT: If a field includes an 'options=[...]' list, you MUST pick a value EXACTLY from that list "
            "(verbatim, including capitalization). Do not invent new options.\n"
            "IMPORTANT: Some fields include input constraints. If a field has 'pattern=...' "
            "(an HTML regex), the value you generate MUST fully match that regex. If it has "
            "'maxlength=N', the value must be at most N characters long. If it has 'placeholder=...', "
            "follow the format shown in that example (e.g. phone, date, or ID formatting).\n"
            "IMPORTANT: For any date field (kind=date), format the value as ISO 8601 'YYYY-MM-DD'.\n\n"
            f"Locale: {context.language}, country: {context.country_hint}, "
            f"currency: {context.currency}, domain: {context.domain}\n"
            "Fields (one per line — selector | kind | label | required, plus any of "
            "options | placeholder | pattern | maxlength | min | max):\n"
            f"{field_lines}\n"
            "Return a JSON object 'values' mapping each field's selector to the value to type into it."
)

        result = await self.llm.structured(prompt, FormFill)
        return result.values
    
    def edge_cases(self, element: Element) -> list[str]:
        return UNIVERSAL + KIND_SPECIFIC.get(element.semantic_kind, [])


_SKIP_INPUT_TYPES = {
    "submit", "button", "reset", "hidden", "image", "file"
}

def fillable(elements):
    out = []
    for el in elements:
        if not el.visible or el.disabled:
            continue
        if el.tag in ("textarea", "select"):
            out.append(el)
        elif el.widget_type == "mui_select":
            out.append(el)
        elif el.tag == "input" and (el.element_type or "text") not in _SKIP_INPUT_TYPES:
            out.append(el)
    return out

def describe_fields(fields) -> str:
    """One LLM-friendly line per field, listing only the constraints that exist.

    Shared by DataGenerator and TestCaseGenerator so the two never drift apart.
    """
    lines = []
    for e in fields:
        line = f"{e.selector} | kind={e.semantic_kind} | label={e.name} | required={e.required}"
        if e.options:
            line += f" | options={e.options}"
        if e.placeholder:
            line += f" | placeholder={e.placeholder}"
        if e.pattern:
            line += f" | pattern={e.pattern}"
        if e.max_length:
            line += f" | maxlength={e.max_length}"
        if e.min_value:
            line += f" | min={e.min_value}"
        if e.max_value:
            line += f" | max={e.max_value}"
        lines.append(line)
    return "\n".join(lines)