"""Mapped insert for warehouse creation; the caller owns audit and commit."""
from sqlalchemy.orm import Session

from app.libs.enums.inventory import WarehouseType
from app.schemas.inventory.inventory import Warehouse


def insert_warehouse(
    db: Session, *, name: str, type: WarehouseType, department_id: int | None,
) -> Warehouse:
    """Use the supplied Session and existing String/FK storage unchanged."""
    warehouse = Warehouse(name=name, type=type.value, department_id=department_id)
    db.add(warehouse)
    db.flush()
    return warehouse
