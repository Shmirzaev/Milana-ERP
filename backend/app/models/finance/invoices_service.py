"""Invoice issuance for the finance and sales invoice endpoints.

Contract for `create_order_invoice`:
* input: a validated `InvoiceIn` plus the acting user
* output: the invoice of that sales order, or the invoice it already has
* refusals: 404 when the sales order does not exist, 422 when the resolved
  amount cannot be stored in `invoices.amount`
* records: one `invoices` row and one `Invoice` audit row
* lock order: the parent `sales_orders` row under NO KEY UPDATE, taken before
  the invoice existence check
* transaction owner: this operation

Contract for `generate_order_invoice`:
* input: a sales order id plus the acting user
* output: the `InvoiceGenerationOut` envelope of that sales order
* refusals: 404 when the sales order does not exist, 400 when the order status
  is not invoiceable, 422 when the resolved total is not representable in cents
* records: one `invoices` row and one `Invoice` audit row
* lock order: the parent `sales_orders` row under NO KEY UPDATE, taken before
  the invoice existence check
* transaction owner: this operation
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.sales.invoice_generation_output import InvoiceGenerationOut
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.enums.finance import InvoiceStatus
from app.libs.enums.sales import SalesOrderStatus
from app.models.audit_service import log_action
from app.models.numbering_service import next_invoice_no
from app.models.payments_service import invoice_payment_status
from app.schemas import Invoice, SalesOrder, User
from app.schemas.finance.invoice_persistence import insert_order_invoice

# `invoices.amount` is NUMERIC(14, 2), so the largest storable amount is 999999999999.99
# and the smallest non-zero one is one cent.
INVOICE_AMOUNT_MAX = Decimal("999999999999.99")
INVOICE_AMOUNT_CENT = Decimal("0.01")

# Sales-order statuses the sales entry point may invoice from.
INVOICEABLE_ORDER_STATUSES: frozenset[SalesOrderStatus] = frozenset({
    SalesOrderStatus.CONFIRMED, SalesOrderStatus.IN_PRODUCTION,
    SalesOrderStatus.CUTTING, SalesOrderStatus.SEWING,
    SalesOrderStatus.PACKAGING, SalesOrderStatus.STORAGE,
    SalesOrderStatus.READY, SalesOrderStatus.RESERVED,
    SalesOrderStatus.SHIPPED, SalesOrderStatus.DELIVERED,
    SalesOrderStatus.PLANNING, SalesOrderStatus.PLANNING_APPROVED,
    SalesOrderStatus.PRODUCTION,
})


def lock_sales_order(db: Session, sales_order_id: int) -> SalesOrder | None:
    """Read one sales order under NO KEY UPDATE, refreshing the row.

    The invoice existence check is serialized on the parent order, and NO KEY
    UPDATE stays compatible with the invoice insert's foreign-key check.
    """
    return (
        db.query(SalesOrder)
        .filter(SalesOrder.id == sales_order_id)
        .populate_existing()
        .with_for_update(of=SalesOrder, key_share=True)
        .first()
    )


def storable_invoice_amount(value: object) -> Decimal:
    """Reduce a resolved invoice amount to what the storage column can hold.

    `InvoiceIn.amount` is already storage-bounded, but an omitted amount falls back
    to the stored `sales_orders.total_amount`, which is a database value rather than
    a validated request field. Both paths go through this check so a nonfinite,
    out-of-column or sub-cent total is rejected before the invoice insert. The
    Sales generator resolves the invoice number first in the same transaction.
    """
    try:
        amount = Decimal(str(value if value is not None else 0))
        if not amount.is_finite() or amount < 0 or amount > INVOICE_AMOUNT_MAX:
            raise ValueError
        if amount != amount.quantize(INVOICE_AMOUNT_CENT):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "Invoice amount must be finite and representable in cents") from None
    return amount.quantize(INVOICE_AMOUNT_CENT)


def create_order_invoice(db: Session, payload: InvoiceIn, actor: User) -> Invoice:
    """Issue the invoice of one sales order, or return the invoice it already has.

    An existing invoice is returned as it is, including a reversed one.
    """
    so = lock_sales_order(db, payload.sales_order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == payload.sales_order_id).order_by(Invoice.id.desc()).first()
    if existing:
        return existing
    amount = storable_invoice_amount(payload.amount if payload.amount is not None else so.total_amount)
    inv = insert_order_invoice(
        db,
        sales_order_id=payload.sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=amount,
        status=invoice_payment_status(amount, 0),
        issued_at=datetime.now(timezone.utc),
    )
    log_action(db, actor, "create", "Invoice", inv.id, new_value={"invoice_no": inv.invoice_no})
    db.commit()
    db.refresh(inv)
    return inv


def generate_order_invoice(db: Session, sales_order_id: int, actor: User) -> InvoiceGenerationOut:
    """Issue the invoice of one sales order from the sales entry point.

    An existing invoice is returned as it is, including a reversed one, and no
    invoice, audit row or commit is written for it. The amount is the stored
    order total and the status is always `unpaid`, which is what the sales
    entry point has always issued.
    """
    so = lock_sales_order(db, sales_order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    # SalesOrder.status remains a mapped string. Keep its old normalization and
    # refusal message at this boundary, including for unknown stored values.
    try:
        order_status = SalesOrderStatus(str(so.status or ""))
    except ValueError:
        order_status = None
    if order_status not in INVOICEABLE_ORDER_STATUSES:
        raise HTTPException(400, f"Cannot generate invoice for order in status '{so.status}'")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == sales_order_id).order_by(Invoice.id.desc()).first()
    if existing:
        return _invoice_generation_result(existing, created_existing=True)
    inv = insert_order_invoice(
        db,
        sales_order_id=sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=storable_invoice_amount(so.total_amount),
        status=InvoiceStatus.UNPAID,
        issued_at=datetime.now(timezone.utc),
    )
    log_action(db, actor, "generate_invoice", "Invoice", inv.id, new_value={"sales_order_id": sales_order_id, "amount": float(inv.amount or 0)})
    db.commit()
    db.refresh(inv)
    return _invoice_generation_result(inv, created_existing=False)


def _invoice_generation_result(invoice: Invoice, *, created_existing: bool) -> InvoiceGenerationOut:
    """Shape one invoice the way the sales entry point returns it."""
    return InvoiceGenerationOut(
        id=invoice.id,
        sales_order_id=invoice.sales_order_id,
        invoice_no=invoice.invoice_no,
        amount=float(invoice.amount or 0),
        status=invoice.status,
        issued_at=invoice.issued_at,
        due_date=invoice.due_date,
        created_existing=created_existing,
    )
