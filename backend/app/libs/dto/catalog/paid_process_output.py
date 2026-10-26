from pydantic import BaseModel

from app.libs.enums.catalog import PaidProcessSection


class PaidProcessOut(BaseModel):
    id: int
    code: str
    name: str
    section: PaidProcessSection
