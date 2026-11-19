from typing import Optional

from app.libs.dto.common import ORMModel


class PartyOut(ORMModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class PartyPageOut(ORMModel):
    rows: list[PartyOut]
    total: int
    page: int
    page_size: int
