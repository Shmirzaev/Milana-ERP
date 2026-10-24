"""Invoice issuance for the finance invoice endpoint.

Contract for `create_order_invoice`:
* input: a validated `InvoiceIn` plus the acting user
* output: the invoice of that sales order, or the invoice it already has
* refusals: 404 when the sales order does not exist, 422 when the resolved
  amount cannot be stored in `invoices.amount`
* records: one `invoices` row and one `Invoice` audit row
* lock order: the parent `sales_orders` row under NO KEY UPDATE, taken before
  the invoice existence check
* transaction owner: this operation
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.sales.sales import InvoiceIn
from app.models.audit_service import log_action
from app.models.numbering_service import next_invoice_no
from app.models.payments_service import invoice_payment_status
from app.schemas import Invoice, SalesOrder, User

# `invoices.amount` is NUMERIC(14, 2), so the largest storable amount is 999999999999.99
# and the smallest non-zero one is one cent.
INVOICE_AMOUNT_MAX = Decimal("999999999999.99")
INVOICE_AMOUNT_CENT = Decimal("0.01")


def storable_invoice_amount(value: object) -> Decimal:
    """Reduce a resolved invoice amount to what the storage column can hold.

    `InvoiceIn.amount` is already storage-bounded, but an omitted amount falls back
    to the stored `sales_orders.total_amount`, which is a database value rather than
    a validated request field. Both paths go through this check so a nonfinite,
    out-of-column or sub-cent total is rejected before any write.
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
    # Serialize the existence check even when there is no invoice row to lock.
    # NO KEY UPDATE stays compatible with invoice-insert foreign-key checks.
    so = (
        db.query(SalesOrder)
        .filter(SalesOrder.id == payload.sales_order_id)
        .populate_existing()
        .with_for_update(of=SalesOrder, key_share=True)
        .first()
    )
    if not so:
        raise HTTPException(404, "Sales order not found")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == payload.sales_order_id).order_by(Invoice.id.desc()).first()
    if existing:
        return existing
    amount = storable_invoice_amount(payload.amount if payload.amount is not None else so.total_amount)
    inv = Invoice(
        sales_order_id=payload.sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=amount,
        status=invoice_payment_status(amount, 0),
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    log_action(db, actor, "create", "Invoice", inv.id, new_value={"invoice_no": inv.invoice_no})
    db.commit()
    db.refresh(inv)
    return inv
