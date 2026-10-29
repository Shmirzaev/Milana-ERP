"""Warehouse request contract."""

from typing import Optional

from pydantic import BaseModel
from app.libs.dto.inventory.warehouse_create_type import WarehouseCreateType


class WarehouseIn(BaseModel):
    name: str
    type: WarehouseCreateType
    department_id: Optional[int] = None
