from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["safe", "destructive", "uncertain"]

class SafetyVerdict(BaseModel):
    risk: RiskLevel = "safe"
    reason: str = ""
    signals: list[str] = Field(default_factory=list)
    