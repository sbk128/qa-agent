from src.data.edge_cases import KIND_SPECIFIC, UNIVERSAL
from src.data.generator import describe_fields, fillable
from src.llm import LLMProvider
from src.models.context import InferredContext
from src.models.element import Element
from src.models.testcase import TestCase, TestSuite


# Injecting a nasty literal only makes sense for free-text fields — dropdowns /
# radios / checkboxes auto-repair to a valid choice, so junk there never sticks.
def _is_free_text(f: Element) -> bool:
    if f.widget_type == "mui_select":
        return False
    if f.tag == "select":
        return False
    if f.element_type in ("radio", "checkbox"):
        return False
    return True


def _label_for(value: str) -> str:
    if value == "":
        return "empty"
    if value.strip() == "":
        return "whitespace"
    if len(value) > 40:
        return f"{len(value)}-char string"
    return value


_MAX_PER_FIELD = 2   # cap injected cases per field so big forms don't explode


def build_edge_cases(fields, baseline: dict[str, str]) -> list[TestCase]:
    """Genuinely-invalid cases built from the static edge_cases library.

    Take the valid happy-path `baseline` and corrupt EXACTLY ONE field with a real
    nasty value (XSS, SQLi, a 10k-char string, a bad email/date…). One bad field at
    a time keeps any rejection attributable. `expected="rejected"` is a lightweight
    oracle: a genuinely-bad value SHOULD be rejected — if the form accepts it, that's
    a real under-validation finding.
    """
    cases: list[TestCase] = []
    for f in fields:
        if not _is_free_text(f):
            continue
        # Field-specific nasties first (most relevant), then the headline universal
        # ones — so each field gets a diverse, targeted set within the cap.
        bad_values = (KIND_SPECIFIC.get(f.semantic_kind, []) + UNIVERSAL)[:_MAX_PER_FIELD]
        for bad in bad_values:
            data = dict(baseline)
            data[f.selector] = bad
            cases.append(TestCase(
                name=f"Bad {f.name}: {_label_for(bad)}",
                category="edge",
                description=f"Inject {_label_for(bad)!r} into '{f.name}', everything else valid.",
                field_values=data,
                expected="rejected",
                rationale="Genuinely-invalid input should be rejected; acceptance = under-validation.",
            ))
    return cases


class TestCaseGenerator:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def generate(self, elements: list[Element], context: InferredContext) -> list[TestCase]: 
        fields = fillable(elements)
        if not fields:
            return []
    
        field_lines = describe_fields(fields)
        prompt = (
            "You are a senior QA engineer designing a test plan for a web form.\n\n"
            "Form fields (one per line — selector | kind | label | required, plus any of "
            "options | placeholder | pattern | maxlength | min | max):\n"
            f"{field_lines}\n\n"
            f"Locale: language={context.language}, country={context.country_hint}, "
            f"domain={context.domain}.\n\n"
            "For the HAPPY PATH case, every value MUST satisfy the field's constraints: "
            "if a field has 'options=[...]', pick a value EXACTLY from that list (verbatim); "
            "if it has 'pattern=...', the value must match that regex; if 'maxlength=N', stay "
            "within N characters; if 'placeholder=...', follow that format. For date fields "
            "(kind=date) use ISO 8601 'YYYY-MM-DD', and respect any 'min'/'max' bounds (e.g. an "
            "appointment date must be on or after 'min').\n\n"
            "Generate a suite of test cases covering:\n"
            "1. HAPPY PATH — all fields valid and consistent (one coherent persona).\n"
            "2. EDGE CASES — empty required field, invalid format (bad email, impossible "
            "date), over-long input, special characters, boundary values.\n"
            "3. SCENARIOS — creative combinations a real tester would try (partial fills, "
            "one required field omitted, type confusion).\n\n"
            "For each case provide: name, category (happy/edge/scenario), description, "
            "field_values (map of field selector -> value; omit fields you leave blank), "
            "expected ('accepted'/'rejected'/'unknown' — what the form SHOULD do), and a "
            "one-sentence rationale.\n"
            "Return JSON matching the schema."
        )
        suite = await self.llm.structured(prompt, TestSuite)
        cases = suite.cases

        # Add genuinely-nasty edge cases from the static library, injected one bad
        # field at a time onto the LLM's valid happy-path baseline. The LLM is good
        # at *which* scenarios to try but weak at emitting *genuinely* bad values
        # (it truncates the 10k-char string, writes polite fakes) — so we supply
        # those deterministically instead of trusting it.
        happy = next((c for c in cases if c.category == "happy" and c.field_values), None)
        if happy:
            cases = cases + build_edge_cases(fields, happy.field_values)
        return cases
    
        
        