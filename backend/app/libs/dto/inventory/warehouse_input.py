"""Warehouse request contract."""

from typing import Literal, Optional

from pydantic import BaseModel


class WarehouseIn(BaseModel):
    name: str
    type: Literal[
        "fabric_storage",
        "accessory_storage",
        "packaging",
        "cutting",
        "eco_cotton_cutting",
        "printing",
        "sewing",
        "besttex_packaging",
        "eco_cotton_packaging",
        "finished_goods",
        "waste",
    ]
    department_id: Optional[int] = None
