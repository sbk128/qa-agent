from typing import Literal

from pydantic import BaseModel


class ActionResult(BaseModel):
    action: Literal["fill", "click", "skip"]
    selector: str
    value: str | None = None
    ok: bool = True
    # True when the executor could not use the requested value and substituted a
    # different valid one (e.g. picked option #1 because the asked-for label wasn't
    # in the dropdown). The runner treats a fallback on a field the case is probing
    # as "we didn't actually test what we meant to".
    fallback: bool = False
    detail: str = ""
