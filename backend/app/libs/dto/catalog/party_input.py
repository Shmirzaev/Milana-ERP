from typing import Optional

from pydantic import BaseModel, Field


class PartyIn(BaseModel):
    name: str = Field(max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = None
    notes: Optional[str] = None
