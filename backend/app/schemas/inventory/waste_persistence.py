"""Schema-owned WasteRecord construction for Inventory operations."""
from __future__ import annotations

from app.schemas.inventory.waste import WasteRecord
from sqlalchemy.orm import Session


def insert_waste_record(
    db: Session, *, production_order_id: int | None, work_order_id: int | None,
    source_department_id: int | None, item_id: int | None, batch_id: int | None,
    waste_type: str, quantity: float, unit: str, reason: str | None,
    created_by: int | None, sellable: bool = False, estimated_value: float = 0,
    status: str = "recorded",
) -> WasteRecord:
    row = WasteRecord(
        production_order_id=production_order_id, work_order_id=work_order_id,
        source_department_id=source_department_id, item_id=item_id, batch_id=batch_id,
        waste_type=waste_type, quantity=quantity, unit=unit, reason=reason,
        sellable=sellable, estimated_value=estimated_value, status=status,
        created_by=created_by,
    )
    db.add(row)
    return row
