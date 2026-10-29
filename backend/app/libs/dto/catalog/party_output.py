from typing import Optional

from app.libs.dto.common import ORMModel


class PartyOut(ORMModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
