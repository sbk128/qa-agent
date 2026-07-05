from typing import Literal

from pydantic import BaseModel

SemanticKind = Literal["email", "phone", "date", "name", "address",
    "currency", "search", "password", "unknown"]

WidgetType = Literal["native", "mui_select"]

class Element(BaseModel):
    tag: str           # "input", "button", "a", "select", "textarea"
    element_type: str | None = None   # for inputs: "email", "text", "password", etc.
    name: str          # the human label
    selector: str      # a CSS selector that uniquely identifies it
    required: bool = False
    visible: bool = True
    disabled: bool = False
    readonly: bool = False
    semantic_kind: SemanticKind = "unknown"
    widget_type: WidgetType = "native"
    options: list[str] | None = None
    in_form: bool = False
    placeholder: str | None = None
    pattern: str | None = None
    max_length: int | None = None
    min_value: str |  None = None
    max_value: str | None = None

