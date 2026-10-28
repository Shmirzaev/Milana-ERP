from typing import Optional

from pydantic import BaseModel


class BrandIn(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool = True
