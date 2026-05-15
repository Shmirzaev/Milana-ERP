from __future__ import annotations

from datetime import timezone, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Invoice, Payment, SalesOrder
from app.schemas.integrations import OneCSyncIn
from app.services.numbering import next_invoice_no

SOURCE_1C = "1c"


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_sales_order(db: Session, sales_order_id: int | None, sales_order_no: str | None) -> SalesOrder | None:
    if sales_order_id:
        return db.get(SalesOrder, sales_order_id)
    if sales_order_no:
        return db.query(SalesOrder).filter(SalesOrder.order_no == sales_order_no).first()
    return None


def _resolve_invoice(
    db: Session,
    invoice_id: int | None,
    invoice_no: str | None,
    invoice_external_id: str | None,
) -> Invoice | None:
    if invoice_id:
        inv = db.get(Invoice, invoice_id)
        if inv:
            return inv
    if invoice_external_id:
        inv = db.query(Invoice).filter(
            Invoice.external_source == SOURCE_1C,
            Invoice.external_id == invoice_external_id,
        ).first()
        if inv:
            return inv
    if invoice_no:
        inv = db.query(Invoice).filter(Invoice.invoice_no == invoice_no).first()
        if inv:
            return inv
    return None


def _refresh_invoice_status(db: Session, invoice: Invoice) -> None:
    total_paid = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == invoice.id).scalar() or 0
    total_paid = float(total_paid)
    amount = float(invoice.amount)
    if total_paid >= amount:
        invoice.status = "paid"
    elif total_paid > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "unpaid"


def sync_from_1c(db: Session, payload: OneCSyncIn) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "invoices_created": 0,
        "invoices_updated": 0,
        "payments_created": 0,
        "payments_updated": 0,
        "errors": [],
    }

    for i, row in enumerate(payload.invoices):
        try:
            sales_order = _resolve_sales_order(db, row.sales_order_id, row.sales_order_no)
            if not sales_order:
                raise ValueError("sales order not found (provide sales_order_id or sales_order_no)")
            invoice = db.query(Invoice).filter(
                Invoice.external_source == SOURCE_1C,
                Invoice.external_id == row.external_id,
            ).first()
            is_new = invoice is None
            if is_new:
                invoice = Invoice(
                    sales_order_id=sales_order.id,
                    invoice_no=row.invoice_no or next_invoice_no(db),
                    external_source=SOURCE_1C,
                    external_id=row.external_id,
                    issued_at=_as_utc(row.issued_at),
                    due_date=_as_utc(row.due_date),
                )
                db.add(invoice)
            else:
                invoice.sales_order_id = sales_order.id
                if row.invoice_no:
                    invoice.invoice_no = row.invoice_no
                invoice.issued_at = _as_utc(row.issued_at)
                invoice.due_date = _as_utc(row.due_date)

            invoice.amount = row.amount
            invoice.status = row.status
            db.flush()

            if is_new:
                summary["invoices_created"] += 1
            else:
                summary["invoices_updated"] += 1
        except Exception as e:
            summary["errors"].append({"type": "invoice", "index": i, "external_id": row.external_id, "error": str(e)})

    for i, row in enumerate(payload.payments):
        try:
            invoice = _resolve_invoice(db, row.invoice_id, row.invoice_no, row.invoice_external_id)
            if not invoice:
                raise ValueError("invoice not found (provide invoice_id, invoice_no, or invoice_external_id)")
            payment = db.query(Payment).filter(
                Payment.external_source == SOURCE_1C,
                Payment.external_id == row.external_id,
            ).first()
            is_new = payment is None
            if is_new:
                payment = Payment(
                    invoice_id=invoice.id,
                    external_source=SOURCE_1C,
                    external_id=row.external_id,
                )
                db.add(payment)
            else:
                payment.invoice_id = invoice.id

            payment.amount = row.amount
            payment.payment_method = row.payment_method
            payment.paid_at = _as_utc(row.paid_at)
            payment.notes = row.notes
            db.flush()

            _refresh_invoice_status(db, invoice)

            if is_new:
                summary["payments_created"] += 1
            else:
                summary["payments_updated"] += 1
        except Exception as e:
            summary["errors"].append({"type": "payment", "index": i, "external_id": row.external_id, "error": str(e)})

    return summary

