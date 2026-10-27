"""Schema-owned persistence for the sales-order operations.

These operations own the mapped construction, add/flush and mapped-field
mutations for `sales_orders` and `sales_order_items` inside the
sales-order creation and header-edit operations.

They use the caller's Session, never commit, never open or close a
transaction, never swallow an error and never import a service or a route.
The business service keeps the rules, the permissions, the calculations and
the single outer commit.

Only Sales-owned tables are written here. The branded-stock reservation also
writes `finished_goods_stock` and `stock_reservations`, which belong to
Fulfillment. The approved public reserve_pieces/reserve_packs operations in
models/fulfillment/stock_service.py own that selection and delegate its writes
to schemas/fulfillment/stock_persistence.py in this same transaction.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.libs.types.sales_order import SalesOrderHeaderChanges, StoredSalesAttachment
from app.schemas.sales.sales import SalesOrder, SalesOrderItem


def create_sales_order_row(
    db: Session,
    *,
    order_no: str,
    customer_id: int | None,
    order_type: SalesOrderType,
    status: SalesOrderStatus,
    deadline: datetime | None,
    printing_instructions: str | None,
    printing_attachments: list[StoredSalesAttachment] | None,
    notes: str | None,
    created_by: int | None,
) -> SalesOrder:
    """Insert one sales order row with its mapped fields."""
    order = SalesOrder(
        order_no=order_no,
        customer_id=customer_id,
        order_type=order_type.value,
        status=status.value,
        deadline=deadline,
        printing_instructions=printing_instructions,
        printing_attachments=printing_attachments,
        notes=notes,
        created_by=created_by,
    )
    db.add(order)
    db.flush()
    return order


def create_sales_order_item(
    db: Session,
    *,
    sales_order_id: int,
    model_id: int | None,
    brand_id: int | None,
    collection_id: int | None,
    color: str,
    size: str,
    quantity: int,
    requested_pack_count: int | None,
    unit_price: float,
    printing_required: bool,
    source_type: SalesOrderItemSourceType,
    notes: str | None,
) -> SalesOrderItem:
    """Insert one sales-order line with its mapped fields."""
    line = SalesOrderItem(
        sales_order_id=sales_order_id,
        model_id=model_id,
        brand_id=brand_id,
        collection_id=collection_id,
        color=color,
        size=size,
        quantity=quantity,
        requested_pack_count=requested_pack_count,
        unit_price=unit_price,
        printing_required=printing_required,
        source_type=source_type.value,
        notes=notes,
    )
    db.add(line)
    return line


def set_sales_order_total(db: Session, order: SalesOrder, total_amount: float | Decimal) -> None:
    """Write the calculated order total."""
    order.total_amount = total_amount


def set_sales_order_status(db: Session, order: SalesOrder, status: SalesOrderStatus) -> None:
    """Write the sales-order status."""
    order.status = status.value


def append_sales_order_note(db: Session, order: SalesOrder, note: str) -> None:
    """Append one line to the order notes, keeping the existing notes."""
    order.notes = f"{order.notes}\n{note}".strip() if order.notes else note


def set_sales_order_item_quantity(db: Session, line: SalesOrderItem, quantity: int) -> None:
    """Write the quantity of one sales-order line."""
    line.quantity = quantity


def apply_sales_order_header_changes(
    db: Session, order: SalesOrder, changes: SalesOrderHeaderChanges
) -> None:
    """Write the supplied sales-order header columns.

    Only the columns the caller supplied are assigned. An absent key leaves the
    stored value untouched; a present key holding null clears it. The workflow
    status is never written here: it belongs to the workflow commands.

    This operation uses the caller's Session, never commits, never opens or
    closes a transaction and never flushes on its own.
    """
    if "customer_id" in changes:
        order.customer_id = changes["customer_id"]
    if "deadline" in changes:
        order.deadline = changes["deadline"]
    if "printing_instructions" in changes:
        order.printing_instructions = changes["printing_instructions"]
    if "printing_attachments" in changes:
        order.printing_attachments = changes["printing_attachments"]
    if "notes" in changes:
        order.notes = changes["notes"]
