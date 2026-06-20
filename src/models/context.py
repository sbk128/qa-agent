from typing import Literal
from pydantic import BaseModel

class InferredContext(BaseModel): 
    # Setting up defaults in case LLM omits any field we get a 
    # fallback with default value instad of a crash
    language: str = "en"
    country_hint : str | None = None
    currency: str | None = None
    domain: Literal[
        "e-commerce", "cms", "healthcare", "finance", "generic", "crm", 
    ] = "generic"
    is_authenticated: bool = False
    app_type: Literal["spa", "mpa", "wizard", "dashboard"] = "mpa"
