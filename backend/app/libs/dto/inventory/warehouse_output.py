"""Warehouse response contract."""

from typing import Optional

from app.libs.dto.common import ORMModel


class WarehouseOut(ORMModel):
    id: int
    name: str
    type: str
    department_id: Optional[int] = None
