from typing import Literal

from pydantic import BaseModel


class Finding(BaseModel):
    severity: Literal["critical", "high", "medium", "low", "info"] = "info"
    category: Literal["js_error", "network_error", "validation", "ui_state", "other"] = "other"
    title: str
    description: str = ""
    url: str = ""
