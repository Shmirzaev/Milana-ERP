from typing import Optional

from app.libs.dto.common import ORMModel


class CollectionOut(ORMModel):
    id: int
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str
