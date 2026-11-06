"""Sales pack-count coordination; physical allocation belongs to Fulfillment."""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.libs.enums.sales import SalesOrderStatus
from app.libs.types.stock_reservation import PackDemand, ReservationSummary
from app.models.fulfillment.stock_service import has_order_reservations, reserve_packs
from app.schemas import SalesOrder, SalesOrderItem
from app.schemas.sales.sales_order_persistence import (
    set_sales_order_item_quantity, set_sales_order_status, set_sales_order_total,
)


def reserve_ready_packs(db: Session, *, so: SalesOrder, lines: list[SalesOrderItem], user_id: int) -> list[ReservationSummary]:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.query(SalesOrder).filter(SalesOrder.id == so.id).with_for_update(of=SalesOrder).first()
    if has_order_reservations(db, so.id):
        raise HTTPException(409, "Stock has already been reserved for this sales order")
    # Opaque request-local keys work for both new unflushed and persisted lines.
    # They avoid adding a flush merely to obtain database IDs for the boundary.
    lines_by_key = {str(index): line for index, line in enumerate(lines)}
    result = reserve_packs(
        db, sales_order_id=so.id, reserved_by=user_id,
        demands=tuple(PackDemand(key, line.model_id, line.brand_id, line.requested_pack_count)
                      for key, line in lines_by_key.items()),
    )
    for key, quantity in result.piece_quantities_by_demand.items():
        set_sales_order_item_quantity(db, lines_by_key[key], quantity)
    set_sales_order_total(db, so, sum(Decimal(str(line.unit_price)) * line.quantity for line in lines))
    set_sales_order_status(db, so, SalesOrderStatus.READY)
    return list(result.reservations)
