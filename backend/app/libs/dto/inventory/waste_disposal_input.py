"""Waste disposal request contract."""

from typing import Optional

from pydantic import BaseModel


class WasteDisposalIn(BaseModel):
    reason: Optional[str] = None
