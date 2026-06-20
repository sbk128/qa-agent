from src.llm import LLMProvider
from src.models.testcase import TestSuite, TestCase
from src.models.element import Element
from src.models.context import InferredContext
from src.data.generator import fillable, describe_fields

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
        return suite.cases
    
        
        