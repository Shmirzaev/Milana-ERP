"""Schema-owned persistence for purchase requests and their lines.

These helpers own the mapped construction and add of the rows the purchase
request create operation writes. The business rules, the reference checks, the
quantity rules, the flush boundaries and the outer transaction stay in
`app/models/purchasing_service.py` and `app/models/purchasing/requests_service.py`.
"""

from sqlalchemy.orm import Session

from app.libs.enums.purchasing import PurchaseRequestStatus
from app.schemas.purchasing.purchasing import PurchaseRequest, PurchaseRequestLine


def add_purchase_request_row(
    db: Session,
    *,
    request_no: str,
    status: PurchaseRequestStatus,
    sales_order_id: int | None,
    production_order_id: int | None,
    requested_by: int | None,
    notes: str | None,
) -> PurchaseRequest:
    """Add one purchase request header row to the caller's session."""
    row = PurchaseRequest(
        request_no=request_no,
        status=status.value,
        sales_order_id=sales_order_id,
        production_order_id=production_order_id,
        requested_by=requested_by,
        notes=notes,
    )
    db.add(row)
    return row


def add_purchase_request_line_row(
    db: Session,
    *,
    purchase_request_id: int,
    item_id: int,
    required_quantity: float,
    requested_quantity: float,
    unit: str,
    available_quantity: float,
    shortage_quantity: float,
    preferred_supplier_id: int | None,
    material_name: str | None,
    photo_url: str | None,
    notes: str | None,
) -> PurchaseRequestLine:
    """Add one purchase request line row to the caller's session."""
    row = PurchaseRequestLine(
        purchase_request_id=purchase_request_id,
        item_id=item_id,
        required_quantity=required_quantity,
        requested_quantity=requested_quantity,
        unit=unit,
        available_quantity=available_quantity,
        shortage_quantity=shortage_quantity,
        preferred_supplier_id=preferred_supplier_id,
        material_name=material_name,
        photo_url=photo_url,
        notes=notes,
    )
    db.add(row)
    return row
