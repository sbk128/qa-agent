from src.llm import LLMProvider, SMALL_MODEL
from src.models.element import Element
from src.models.safety import SafetyVerdict
from src.safety.patterns import DESTRUCTIVE, AMBIGUOUS

# Buttons that START with one of these are data-entry/create actions — safe to click
# even if the label contains a "destructive" word. e.g. "Add Payment" / "Save Charge"
# are recording data, not the irreversible "Pay now" / "Charge card" the rules target.
_SAFE_CREATE_PREFIXES = ("add ", "create ", "new ", "save ", "register ", "update ", "edit ")

class SafetyGate:
    def __init__(self, llm: LLMProvider, allow_all: bool = False) -> None:
        self.llm = llm
        # Sandbox mode: skip the destructive block entirely. For dev/test targets where
        # exercising every action (incl. financial submits like "Submit Transaction") is
        # the point. Off by default — safety stays on for unknown/prod sites.
        self.allow_all = allow_all

    async def evaluate(self, element: Element) -> SafetyVerdict:
        if self.allow_all:
            return SafetyVerdict(risk="safe", reason="sandbox mode (--allow-all): gate disabled")

        text = (element.name or "").lower().strip()

        if text.startswith(_SAFE_CREATE_PREFIXES):
            return SafetyVerdict(risk="safe", reason="create/data-entry action")

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
                