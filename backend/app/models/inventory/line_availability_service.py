"""Fresh per-line stock checks for inventory dispatch writers."""
from sqlalchemy import and_, case, func, select, true
from sqlalchemy.orm import Session

from app.models.inventory_service import ACTIVE_RESERVATION_STATUSES
from app.schemas import MaterialReservation, StockBatch, StockMovement


def line_availability(
    db: Session, batch_id: int, item_id: int, warehouse_id: int | None, *, global_capacity: bool
) -> tuple[float, float]:
    """Read each relevant pool in one statement, including earlier flushed lines."""
    scoped = warehouse_id is not None
    batch_scope = StockBatch.warehouse_id == warehouse_id if scoped else True
    reservation_scope = MaterialReservation.warehouse_id == warehouse_id if scoped else True
    incoming = StockMovement.movement_type.in_(("produce", "return", "adjustment"))
    outgoing = StockMovement.movement_type.in_(("issue", "consume", "waste", "shipment"))
    scoped_in = and_(StockMovement.movement_type.in_(("produce", "return", "adjustment", "transfer")),
                     StockMovement.to_warehouse_id == warehouse_id) if scoped else incoming
    scoped_out = and_(StockMovement.movement_type.in_(("issue", "consume", "waste", "shipment", "transfer")),
                      StockMovement.from_warehouse_id == warehouse_id) if scoped else outgoing
    def zero_sum(expr):
        return func.coalesce(func.sum(expr), 0)
    stocks = select(zero_sum(StockBatch.quantity).label("total"),
                    zero_sum(case((batch_scope, StockBatch.quantity), else_=0)).label("scoped")) \
        .where(StockBatch.item_id == item_id).subquery()
    movements = select(
        zero_sum(case((incoming, StockMovement.quantity), else_=0)).label("incoming"),
        zero_sum(case((outgoing, StockMovement.quantity), else_=0)).label("outgoing"),
        zero_sum(case((scoped_in, StockMovement.quantity), else_=0)).label("scoped_in"),
        zero_sum(case((scoped_out, StockMovement.quantity), else_=0)).label("scoped_out"),
    ).where(StockMovement.item_id == item_id, StockMovement.batch_id.is_(None)).subquery()
    remaining = (MaterialReservation.reserved_quantity - MaterialReservation.consumed_quantity
                 - MaterialReservation.released_quantity)
    reservations = select(
        zero_sum(remaining).label("total"),
        zero_sum(case((reservation_scope, remaining), else_=0)).label("scoped"),
    ).where(MaterialReservation.item_id == item_id,
            MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES)).subquery()
    batch_reservations = select(zero_sum(remaining).label("batch")).where(
        MaterialReservation.stock_batch_id == batch_id,
        MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES)).subquery()
    pools = stocks.join(movements, true()).join(reservations, true()).join(batch_reservations, true())
    (stock_total, stock_scoped, movement_in, movement_out, movement_scoped_in,
     movement_scoped_out, reservation_total, reservation_scoped, reservation_batch) = db.execute(
        select(stocks.c.total, stocks.c.scoped, movements.c.incoming,
               movements.c.outgoing, movements.c.scoped_in, movements.c.scoped_out,
               reservations.c.total, reservations.c.scoped, batch_reservations.c.batch).select_from(pools)
    ).one()
    total = float(stock_total) + float(movement_in) - float(movement_out) - max(0.0, float(reservation_total))
    local = float(stock_scoped) + float(movement_scoped_in) - float(movement_scoped_out) - max(0.0, float(reservation_scoped))
    return max(0.0, float(reservation_batch)), min(total, local) if global_capacity and scoped else local
