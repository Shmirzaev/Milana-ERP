from typing import Optional

from app.libs.dto.common import ORMModel


class ModelColorOut(ORMModel):
    id: int
    color_name: str
    color_code: Optional[str] = None
