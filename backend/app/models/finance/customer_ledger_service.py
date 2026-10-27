"""Customer money operations: order ledger, receipt history and receipts.

Contract for the three customer financial operations:
* input: a customer id, plus a validated `CustomerPaymentIn` and the acting
  user for the write operation
* output: the customer order ledger, the customer receipt history, or the
  serialized receipt of a recorded payment
* refusals: 404 "Customer not found", 400 "Payment amount must be greater than
  zero", 404 "Sales order not found for this customer"
* records: `payments` rows, an `invoices` row when the order has none, one
  `Payment` audit row and the idempotency record
* lock order: idempotency key, parent sales order under NO KEY UPDATE, then
  candidate invoice rows under FOR UPDATE before the batched paid-sum read;
  invoice numbering follows only when the locked order has no invoices
* transaction owner: `record_customer_payment`
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.libs.enums.finance import InvoiceStatus
from app.models.audit_service import log_action
from app.models.finance.invoices_service import lock_sales_order
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.numbering_service import next_invoice_no
from app.models.payments_service import (
    REVERSED_INVOICE_STATUSES,
    create_customer_advance_payment,
    create_invoice_payment,
    invoice_paid_total,
    invoice_payment_status,
    money_decimal,
)
from app.schemas import Customer, Invoice, Payment, SalesOrder, Shipment, User
from app.schemas.finance.invoice_persistence import insert_order_invoice

# Candidate invoice ids per grouped paid-sum read. Bounded so a single payment
# never builds an unbounded IN list, and small enough to stay well inside the
# server parameter limit.
_PAID_SUM_BATCH_SIZE = 400


def list_customer_orders(db: Session, cid: int) -> list[dict]:
    """The customer's sales orders with their invoice and payment ledger."""
    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    rows = db.query(SalesOrder).filter(SalesOrder.customer_id == cid).order_by(SalesOrder.id.desc()).all()
    order_ids = [int(so.id) for so in rows]
    invoices_by_order: dict[int, list[Invoice]] = defaultdict(list)
    payments_by_invoice: dict[int, list[Payment]] = defaultdict(list)
    shipped_order_ids: set[int] = set()

    if order_ids:
        shipped_order_ids = {
            order_id for (order_id,) in db.query(Shipment.sales_order_id).filter(
                Shipment.sales_order_id.in_(order_ids),
                Shipment.status.in_(("shipped", "delivered")),
                Shipment.deleted_at.is_(None),
            ).distinct().all()
        }
        invoices = (
            db.query(Invoice)
            .filter(Invoice.sales_order_id.in_(order_ids))
            .order_by(Invoice.id.asc())
            .all()
        )
        invoice_ids = [int(inv.id) for inv in invoices]
        for inv in invoices:
            invoices_by_order[int(inv.sales_order_id)].append(inv)

        if invoice_ids:
            payments = (
                db.query(Payment)
                .filter(Payment.invoice_id.in_(invoice_ids))
                .order_by(Payment.id.desc())
                .all()
            )
            for payment in payments:
                payments_by_invoice[int(payment.invoice_id)].append(payment)

    return [
        _serialize_customer_order(so, invoices_by_order[int(so.id)], payments_by_invoice,
                                  has_shipped_goods=so.id in shipped_order_ids)
        for so in rows
    ]


def list_customer_payments(db: Session, cid: int) -> list[dict]:
    """The customer's receipts, with the invoice and order they belong to."""
    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    rows = (
        db.query(Payment, Invoice, SalesOrder)
        .outerjoin(Invoice, Invoice.id == Payment.invoice_id)
        .outerjoin(SalesOrder, SalesOrder.id == Invoice.sales_order_id)
        .filter(or_(SalesOrder.customer_id == cid, Payment.customer_id == cid))
        .order_by(Payment.id.desc())
        .all()
    )
    return [
        _serialize_customer_payment(payment, invoice, so)
        for payment, invoice, so in rows
    ]


def record_customer_payment(
    db: Session,
    cid: int,
    payload: CustomerPaymentIn,
    actor: User,
    idempotency_key: str | None = None,
) -> dict:
    """Record a customer receipt, allocating it to an invoice and/or advance.

    The idempotent replay is checked first and returns the stored response
    without touching the ledger. The payment is allocated to the payable
    invoice of the given sales order, and any remaining amount becomes an
    advance.
    """
    fingerprint_payload = {"customer_id": cid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(db, scope="customers.payments", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    if payload.amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero")

    # Serialize the empty-invoice check with both invoice issuance entrypoints.
    # Lock the parent before any invoice rows or numbering lock, using the same
    # Session and outer transaction as the receipt and its audit/retry records.
    sales_order = lock_sales_order(db, payload.sales_order_id) if payload.sales_order_id else None
    if payload.sales_order_id and (not sales_order or int(sales_order.customer_id or 0) != cid):
        raise HTTPException(404, "Sales order not found for this customer")

    payment = None
    invoice = None
    amount_remaining = money_decimal(payload.amount)

    if sales_order:
        invoice = _find_payable_invoice(db, sales_order)
        if not invoice and not _order_has_invoices(db, sales_order):
            invoice = insert_order_invoice(
                db,
                sales_order_id=sales_order.id,
                invoice_no=next_invoice_no(db),
                amount=money_decimal(sales_order.total_amount),
                status=InvoiceStatus.UNPAID,
                issued_at=datetime.now(timezone.utc),
            )

        if invoice:
            invoice_balance = max(money_decimal(invoice.amount) - invoice_paid_total(db, int(invoice.id)), Decimal(0))
            invoice_amount = min(amount_remaining, invoice_balance) if invoice_balance > 0 else 0
            if invoice_amount > 0:
                payment = create_invoice_payment(
                    db,
                    invoice,
                    amount=invoice_amount,
                    customer_id=cid,
                    payment_method=payload.payment_method,
                    paid_at=payload.paid_at,
                    notes=payload.notes,
                )
                amount_remaining -= invoice_amount

    if amount_remaining >= Decimal("0.01"):
        advance_notes = payload.notes
        if sales_order and invoice and payment:
            suffix = f"Advance balance from overpayment on {sales_order.order_no}"
            advance_notes = f"{(advance_notes or '').strip()} {suffix}".strip()
        payment = create_customer_advance_payment(
            db,
            customer_id=cid,
            amount=amount_remaining,
            payment_method=payload.payment_method,
            paid_at=payload.paid_at,
            notes=advance_notes,
        )
        invoice = None
    log_action(
        db,
        actor,
        "create",
        "Payment",
        payment.id,
        new_value={"amount": float(payment.amount), "customer_id": cid, "sales_order_id": sales_order.id if sales_order else None},
    )
    response = _serialize_customer_payment(payment, invoice, sales_order if invoice else None)
    store_idempotent_response(
        db,
        scope="customers.payments",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=actor,
        status_code=201,
    )
    db.commit()
    db.refresh(payment)
    if invoice:
        db.refresh(invoice)
    return response


def _candidate_paid_totals(db: Session, invoice_ids: list[int]) -> dict[int, Decimal]:
    """Sum candidate-invoice receipts in grouped batches, not once per invoice.

    Every total is the same ``func.sum(Payment.amount)`` the per-invoice read
    produced, so a batched total is the identical ``Decimal``: an invoice with no
    receipt is zero rather than missing, and advance rows (no invoice) are never
    included. Callers hold the candidate invoice locks, so every row in the batch
    is read inside the same locks the per-invoice loop used.
    """
    # Seeded so an invoice with no receipt is zero, matching the
    # ``coalesce(sum(...), 0)`` the per-invoice read returned.
    totals: dict[int, Decimal] = {int(invoice_id): Decimal(0) for invoice_id in invoice_ids}
    for start in range(0, len(invoice_ids), _PAID_SUM_BATCH_SIZE):
        chunk = invoice_ids[start:start + _PAID_SUM_BATCH_SIZE]
        grouped = dict(
            db.query(Payment.invoice_id, func.sum(Payment.amount))
            .filter(Payment.invoice_id.in_(chunk))
            .group_by(Payment.invoice_id)
            .all()
        )
        totals.update({int(invoice_id): money_decimal(total or 0) for invoice_id, total in grouped.items()})
    return totals


def _find_payable_invoice(db: Session, sales_order: SalesOrder) -> Invoice | None:
    invoices = (
        db.query(Invoice)
        .filter(Invoice.sales_order_id == sales_order.id)
        .order_by(Invoice.id.asc())
        .populate_existing()
        .with_for_update()
        .all()
    )
    candidates = [invoice for invoice in invoices if invoice.status not in REVERSED_INVOICE_STATUSES]
    # Batched after the locking read above so the sums stay under those locks.
    paid_by_invoice = _candidate_paid_totals(db, [int(invoice.id) for invoice in candidates])
    for invoice in candidates:
        balance_due = money_decimal(invoice.amount) - paid_by_invoice[int(invoice.id)]
        # Settlement changes status only: every real outstanding cent remains
        # payable, including a balance on an invoice displayed as paid.
        if balance_due > 0:
            return invoice
    return None


def _order_has_invoices(db: Session, sales_order: SalesOrder) -> bool:
    return bool(db.query(Invoice.id).filter(Invoice.sales_order_id == sales_order.id).first())


def _serialize_customer_payment(payment: Payment, invoice: Invoice | None, sales_order: SalesOrder | None) -> dict:
    return {
        "id": payment.id,
        "row_key": f"payment-{payment.id}",
        "amount": float(payment.amount or 0),
        "payment_method": payment.payment_method,
        "paid_at": payment.paid_at,
        "notes": payment.notes,
        "order_id": sales_order.id if sales_order else None,
        "order_no": sales_order.order_no if sales_order else None,
        "invoice_id": invoice.id if invoice else None,
        "invoice_no": invoice.invoice_no if invoice else None,
        "invoice_amount": float(invoice.amount or 0) if invoice else None,
        "is_advance": invoice is None,
    }


def _serialize_customer_order(
    so: SalesOrder,
    invoices: list[Invoice],
    payments_by_invoice: dict[int, list[Payment]],
    *,
    has_shipped_goods: bool = False,
) -> dict:
    invoice_payloads: list[dict] = []
    invoice_total = Decimal(0)
    paid_total = Decimal(0)
    last_payment_at = None

    for inv in invoices:
        payments = payments_by_invoice.get(int(inv.id), [])
        payment_payloads = []
        raw_paid_amount = Decimal(0)
        for payment in payments:
            amount = money_decimal(payment.amount)
            raw_paid_amount += amount
            if payment.paid_at and (last_payment_at is None or payment.paid_at > last_payment_at):
                last_payment_at = payment.paid_at
            payment_payloads.append(
                {
                    "id": payment.id,
                    "amount": float(amount),
                    "payment_method": payment.payment_method,
                    "paid_at": payment.paid_at,
                    "notes": payment.notes,
                }
            )

        amount = money_decimal(inv.amount)
        paid_amount = min(raw_paid_amount, amount)
        advance_amount = max(raw_paid_amount - amount, 0)
        if inv.status not in REVERSED_INVOICE_STATUSES:
            invoice_total += amount
            paid_total += paid_amount
        invoice_payloads.append(
            {
                "id": inv.id,
                "invoice_no": inv.invoice_no,
                "amount": float(amount),
                "status": invoice_payment_status(amount, raw_paid_amount, inv.status).value,
                "issued_at": inv.issued_at,
                "due_date": inv.due_date,
                "paid_amount": float(round(paid_amount, 2)),
                "raw_paid_amount": float(round(raw_paid_amount, 2)),
                "advance_amount": float(round(advance_amount, 2)),
                "balance_due": float(round(max(amount - paid_amount, 0), 2)),
                "payments": payment_payloads,
            }
        )

    balance_due = max((invoice_total if invoices else money_decimal(so.total_amount)) - paid_total, 0)

    def payment_status() -> str:
        if not invoices:
            if so.status == "cancelled":
                return "cancelled"
            return "unpaid" if has_shipped_goods and balance_due > 0 else "no_invoice"
        active_invoices = [inv for inv in invoices if inv.status not in REVERSED_INVOICE_STATUSES]
        if not active_invoices:
            has_cancelled = any(inv.status == InvoiceStatus.CANCELLED for inv in invoices)
            return InvoiceStatus.CANCELLED.value if has_cancelled else InvoiceStatus.VOID.value
        status = invoice_payment_status(invoice_total, paid_total)
        return "partial" if status == InvoiceStatus.PARTIALLY_PAID else status.value

    return {
        "id": so.id,
        "order_no": so.order_no,
        "date": so.created_at,
        "total": float(so.total_amount or 0),
        "status": so.status,
        "invoice_total": float(round(invoice_total, 2)),
        "paid_total": float(round(paid_total, 2)),
        "balance_due": float(round(balance_due, 2)),
        "payment_status": payment_status(),
        "last_payment_at": last_payment_at,
        "invoices": invoice_payloads,
    }
