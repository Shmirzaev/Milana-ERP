from typing import Optional

from app.libs.dto.common import ORMModel


class BrandOut(ORMModel):
    id: int
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool
