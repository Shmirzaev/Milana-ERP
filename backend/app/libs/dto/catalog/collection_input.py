from typing import Optional

from pydantic import BaseModel


class CollectionIn(BaseModel):
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str = "draft"
