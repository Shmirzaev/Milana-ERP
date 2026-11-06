from typing import Optional

from pydantic import BaseModel


class ModelSizeIn(BaseModel):
    size: str
    measurement_json: Optional[dict] = None
