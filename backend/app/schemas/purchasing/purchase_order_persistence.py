"""Schema-owned persistence for purchase orders and their lines.

These helpers own the mapped construction of purchase orders and order lines,
and the mapped status change a request makes when it is converted into an
order. The business rules, the reference checks, the quantity and cost rules,
the flush boundaries and the outer transaction stay in
`app/models/purchasing_service.py` and `app/models/purchasing/orders_service.py`
and `app/models/purchasing/requests_service.py`.

Every helper uses the caller's Session and never commits, rolls back, begins a
transaction or flushes on its own.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.purchasing import PurchaseOrderStatus, PurchaseRequestStatus
from app.schemas.purchasing.purchasing import PurchaseOrder, PurchaseOrderLine, PurchaseRequest


def add_purchase_order_row(
    db: Session,
    *,
    po_no: str,
    purchase_request_id: int | None,
    supplier_id: int | None,
    status: PurchaseOrderStatus,
    ordered_by: int | None,
    expected_date: datetime | None,
    notes: str | None,
) -> PurchaseOrder:
    """Add one purchase order header row to the caller's session."""
    row = PurchaseOrder(
        po_no=po_no,
        purchase_request_id=purchase_request_id,
        supplier_id=supplier_id,
        status=status.value,
        ordered_by=ordered_by,
        expected_date=expected_date,
        notes=notes,
    )
    db.add(row)
    return row


def add_purchase_order_line_row(
    db: Session,
    *,
    purchase_order_id: int,
    item_id: int,
    ordered_quantity: float,
    received_quantity: float,
    unit: str,
    unit_cost: Decimal | float,
    warehouse_id: int | None,
    supplier_id: int | None,
    material_name: str | None,
    photo_url: str | None,
    notes: str | None,
) -> PurchaseOrderLine:
    """Add one purchase order line row to the caller's session."""
    row = PurchaseOrderLine(
        purchase_order_id=purchase_order_id,
        item_id=item_id,
        ordered_quantity=ordered_quantity,
        received_quantity=received_quantity,
        unit=unit,
        unit_cost=unit_cost,
        warehouse_id=warehouse_id,
        supplier_id=supplier_id,
        material_name=material_name,
        photo_url=photo_url,
        notes=notes,
    )
    db.add(row)
    return row


def apply_purchase_request_conversion(
    request: PurchaseRequest, *, status: PurchaseRequestStatus
) -> None:
    """Apply the service's conversion decision to the locked request header.

    The caller owns the lock, the flush and the outer transaction.
    """
    request.status = status.value
