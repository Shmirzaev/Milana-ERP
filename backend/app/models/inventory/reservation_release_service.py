"""Transaction-neutral release operation shared by Inventory and Cutting."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.enums.inventory import MaterialReservationStatus
from app.models.inventory_service import EPSILON, _open_reservation_quantity, _reservation_status_for_quantities
from app.schemas import MaterialReservation
from app.schemas.inventory import material_reservation_persistence


def release_material_reservation(db: Session, reservation_id: int) -> MaterialReservation:
    reservation = db.get(MaterialReservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Material reservation not found")
    if reservation.status in (
        MaterialReservationStatus.CANCELLED.value,
        MaterialReservationStatus.RELEASED.value,
        MaterialReservationStatus.CONSUMED.value,
    ):
        raise HTTPException(409, f"Reservation is already {reservation.status}")
    remaining = _open_reservation_quantity(reservation)
    released = float(reservation.released_quantity or 0) + remaining if remaining > EPSILON else None
    status = _reservation_status_for_quantities(
        reservation.reserved_quantity, reservation.consumed_quantity,
        reservation.released_quantity if released is None else released,
    )
    material_reservation_persistence.apply_reservation_release(
        db, reservation, released_quantity=released, status=status,
    )
    db.flush()
    return reservation
