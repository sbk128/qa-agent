from typing import Literal
from pydantic import BaseModel

class ActionResult(BaseModel):
    action: Literal["fill", "click", "skip"]
    selector: str
    value: str | None = None
    ok: bool = True
    detail: str = ""

