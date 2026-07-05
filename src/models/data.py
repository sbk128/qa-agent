from pydantic import BaseModel


class FormFill(BaseModel):
    values: dict[str, str] = {}
    