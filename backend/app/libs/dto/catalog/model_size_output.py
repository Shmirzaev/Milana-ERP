from typing import Optional

from app.libs.dto.common import ORMModel


class ModelSizeOut(ORMModel):
    id: int
    size: str
    measurement_json: Optional[dict] = None
