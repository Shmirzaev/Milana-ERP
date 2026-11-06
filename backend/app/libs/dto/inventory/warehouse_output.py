"""Warehouse response contract."""

from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.dto.inventory.warehouse_create_type import WarehouseCreateType


class WarehouseOut(ORMModel):
    """Legacy list boundary: stored vocabulary is not yet reconciled."""
    id: int
    name: str
    type: str
    department_id: Optional[int] = None


class WarehouseCreatedOut(ORMModel):
    """Only the validated creation operation returns this strict contract."""

    id: int
    name: str
    type: WarehouseCreateType
    department_id: Optional[int] = None
