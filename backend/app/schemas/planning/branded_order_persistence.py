"""Schema-owned persistence for branded planning orders.

The mapped class stays where it is, in `app.schemas.production.production`, and
is imported here. This module owns the mapped insert for the branded planning
order operation and nothing else: it builds the row, adds it to the caller's
Session and flushes it so the row id exists.

It never commits, never opens or begins a transaction, never imports services
or routes and never swallows errors. The calling business service owns the
Session and the single outer transaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.libs.enums.planning import BrandedPlanningOrderStatus, BrandedPlanningOrderType
from app.schemas.production.production import BrandedPlanningOrder


@dataclass(frozen=True)
class BrandedPlanningOrderInsert:
    """The explicit mapped fields of one branded planning order row."""

    order_no: str
    ordered_for_type: BrandedPlanningOrderType
    customer_id: int | None
    ordered_for_name: str
    status: BrandedPlanningOrderStatus
    notes: str | None
    created_by: int | None


def insert_branded_planning_order(
    db: Session,
    command: BrandedPlanningOrderInsert,
) -> BrandedPlanningOrder:
    """Insert one branded planning order and return the flushed row."""
    order = BrandedPlanningOrder(
        order_no=command.order_no,
        ordered_for_type=command.ordered_for_type.value,
        customer_id=command.customer_id,
        ordered_for_name=command.ordered_for_name,
        status=command.status.value,
        notes=command.notes,
        created_by=command.created_by,
    )
    db.add(order)
    db.flush()
    return order
