from typing import Optional

from pydantic import BaseModel


class ModelColorIn(BaseModel):
    color_name: str
    color_code: Optional[str] = None
