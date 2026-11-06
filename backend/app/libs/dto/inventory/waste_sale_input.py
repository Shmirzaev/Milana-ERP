"""Waste sale request contract."""

from pydantic import BaseModel


class WasteSaleIn(BaseModel):
    buyer_name: str
    quantity: float
    unit_price: float
