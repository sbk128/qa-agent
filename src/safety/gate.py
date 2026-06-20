from src.llm import LLMProvider, SMALL_MODEL
from src.models.element import Element
from src.models.safety import SafetyVerdict
from src.safety.patterns import DESTRUCTIVE, AMBIGUOUS

class SafetyGate:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def evaluate(self, element: Element) -> SafetyVerdict:
        text = (element.name or "").lower()

        for word in DESTRUCTIVE:
            if word in text:
                return SafetyVerdict(
                    risk="destructive",
                    reason=f"Text matched danger word: '{word}'",
                    signals=[f"text:{word}"],
                )
        
        for word in AMBIGUOUS:
            if word in text:
                return await self._ask_llm(element)
            
        return SafetyVerdict(risk="safe", reason="No destructive signals"
                             )
    
    async def _ask_llm(self, element: Element) -> SafetyVerdict:
        prompt = (
    "You classify whether a UI action is safe for an autonomous web-testing "
    "agent to click. Choose exactly one risk level:\n"
    "- destructive: clearly causes irreversible data loss, financial charges, "
    "or messages to real people (e.g. 'Delete account', 'Pay now', 'Send invite').\n"
    "- safe: clearly harmless (navigation, search, or submitting/saving an "
    "ordinary form during testing).\n"
    "- uncertain: you cannot tell from the label alone, or it depends on "
    "context you can't see.\n"
    "Only choose 'destructive' when the danger is clear from the label itself. "
    "If you are unsure, choose 'uncertain' — never 'destructive'.\n"
    f"Action label: {element.name!r}\n"
    "Return the risk and a one-sentence reason."
        )
        return await self.llm.structured(prompt, SafetyVerdict, model=SMALL_MODEL)
                