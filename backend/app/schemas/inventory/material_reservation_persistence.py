"""Mapped insert for material reservations; the caller owns audit and commit."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.libs.enums.inventory import (
    MaterialReservationSource,
    MaterialReservationStatus,
    MaterialReservationType,
)
from app.schemas.inventory.inventory import MaterialReservation


def insert_material_reservation(
    db: Session,
    *,
    reservation_no: str,
    production_order_id: int,
    sales_order_id: int | None,
    item_id: int,
    stock_batch_id: int | None,
    warehouse_id: int | None,
    reserved_quantity: float,
    consumed_quantity: float,
    released_quantity: float,
    unit: str,
    status: MaterialReservationStatus,
    reservation_type: MaterialReservationType,
    source: MaterialReservationSource,
    reserved_by: int | None,
    reserved_at: datetime,
    notes: str | None,
) -> MaterialReservation:
    """Use the supplied Session and the unchanged String/FK storage.

    The row is added but not flushed, so the caller keeps the one flush it had
    for the whole batch of reservations.
    """
    reservation = MaterialReservation(
        reservation_no=reservation_no,
        production_order_id=production_order_id,
        sales_order_id=sales_order_id,
        item_id=item_id,
        stock_batch_id=stock_batch_id,
        warehouse_id=warehouse_id,
        reserved_quantity=reserved_quantity,
        consumed_quantity=consumed_quantity,
        released_quantity=released_quantity,
        unit=unit,
        status=status.value,
        reservation_type=reservation_type.value,
        source=source.value,
        reserved_by=reserved_by,
        reserved_at=reserved_at,
        notes=notes,
    )
    db.add(reservation)
    return reservation
