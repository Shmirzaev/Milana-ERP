from __future__ import annotations

from datetime import timezone, datetime
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models import Invoice, Payment, SalesOrder
from app.schemas.integrations import OneCSyncIn
from app.services.numbering import next_invoice_no
from app.core.order_reference import BusinessOrderReferenceLookup, resolve_order_id

SOURCE_1C = "1c"
INVOICE_STATUSES = frozenset({"unpaid", "partially_paid", "paid", "void", "cancelled"})


def _validate_invoice_status(status: str) -> str:
    if status not in INVOICE_STATUSES:
        expected = ", ".join(sorted(INVOICE_STATUSES))
        raise ValueError(f"invalid invoice status; expected one of: {expected}")
    return status


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_sales_order(
    db: Session,
    sales_order_id: int | None,
    sales_order_no: str | None,
    *,
    by_id: dict[int, SalesOrder] | None = None,
    by_no: dict[str, SalesOrder] | None = None,
    reference_lookup: BusinessOrderReferenceLookup | None = None,
) -> SalesOrder | None:
    if sales_order_id:
        return by_id.get(int(sales_order_id)) if by_id is not None else db.get(SalesOrder, sales_order_id)
    if sales_order_no:
        direct = by_no.get(sales_order_no) if by_no is not None else None
        if direct is not None:
            return direct
        order_id = resolve_order_id(db, "SO", sales_order_no, lookup=reference_lookup)
        return (
            by_id.get(int(order_id)) if by_id is not None
            else db.get(SalesOrder, order_id)
        ) if order_id is not None else None
    return None


def _resolve_invoice(
    db: Session,
    invoice_id: int | None,
    invoice_no: str | None,
    invoice_external_id: str | None,
    *,
    by_id: dict[int, Invoice] | None = None,
    by_no: dict[str, Invoice] | None = None,
    by_external_id: dict[str, Invoice] | None = None,
) -> Invoice | None:
    if invoice_id:
        inv = by_id.get(int(invoice_id)) if by_id is not None else db.get(Invoice, invoice_id)
        if inv:
            return inv
    if invoice_external_id:
        inv = (
            by_external_id.get(invoice_external_id)
            if by_external_id is not None
            else db.query(Invoice).filter(
                Invoice.external_source == SOURCE_1C,
                Invoice.external_id == invoice_external_id,
            ).first()
        )
        if inv:
            return inv
    if invoice_no:
        inv = (
            by_no.get(invoice_no)
            if by_no is not None
            else db.query(Invoice).filter(Invoice.invoice_no == invoice_no).first()
        )
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


def _lock_sync_rows(db: Session, payload: OneCSyncIn) -> tuple[list[Payment], list[Invoice]]:
    # Lock the whole batch before any writes, not one old/new pair per row.
    # Manual payment paths only insert new payments after locking invoices;
    # they do not lock these existing payment rows in the opposite order.
    external_payment_ids = {row.external_id for row in payload.payments}
    payments = (
        db.query(Payment)
        .filter(Payment.external_source == SOURCE_1C, Payment.external_id.in_(external_payment_ids))
        .order_by(Payment.id).populate_existing().with_for_update(of=Payment).all()
    ) if external_payment_ids else []
    invoice_ids = {payment.invoice_id for payment in payments if payment.invoice_id is not None}
    invoice_ids.update(row.invoice_id for row in payload.payments if row.invoice_id is not None)
    invoice_nos = {row.invoice_no for row in payload.payments if row.invoice_no}
    external_invoice_ids = {row.external_id for row in payload.invoices}
    external_invoice_ids.update(row.invoice_external_id for row in payload.payments if row.invoice_external_id)
    filters = []
    if invoice_ids:
        filters.append(Invoice.id.in_(invoice_ids))
    if invoice_nos:
        filters.append(Invoice.invoice_no.in_(invoice_nos))
    if external_invoice_ids:
        filters.append(and_(Invoice.external_source == SOURCE_1C, Invoice.external_id.in_(external_invoice_ids)))
    invoices = []
    if filters:
        # Include invoice-import updates, which run before the payment loop.
        # Invoices created by this transaction are not visible to competitors.
        invoices = db.query(Invoice).filter(or_(*filters)).order_by(Invoice.id).populate_existing().with_for_update(of=Invoice).all()
    return payments, invoices


def _sales_order_lookup(
    db: Session, payload: OneCSyncIn,
) -> tuple[dict[int, SalesOrder], dict[str, SalesOrder], BusinessOrderReferenceLookup]:
    order_ids = {int(row.sales_order_id) for row in payload.invoices if row.sales_order_id is not None}
    order_nos = {row.sales_order_no for row in payload.invoices if row.sales_order_no}
    reference_lookup = BusinessOrderReferenceLookup(db, order_nos)
    filters = []
    if order_ids:
        filters.append(SalesOrder.id.in_(order_ids))
    if order_nos:
        filters.append(SalesOrder.order_no.in_(order_nos))
    rows = db.query(SalesOrder).filter(or_(*filters)).all() if filters else []
    by_id = {int(row.id): row for row in rows}
    # Alias targets loaded by the shared reference lookup may not have been in
    # the direct id/reference predicates above.
    for order_no in order_nos:
        order_id = resolve_order_id(db, "SO", order_no, lookup=reference_lookup)
        if order_id is not None and int(order_id) not in by_id:
            alias_row = reference_lookup.by_id("SO", int(order_id))
            if alias_row is not None:
                by_id[int(order_id)] = alias_row
    return by_id, {str(row.order_no): row for row in rows}, reference_lookup


def sync_from_1c(db: Session, payload: OneCSyncIn) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "invoices_created": 0,
        "invoices_updated": 0,
        "payments_created": 0,
        "payments_updated": 0,
        "errors": [],
    }
    # Keep the caller's transaction as the durable batch boundary.  This is
    # especially important on SQLite, where a first SAVEPOINT can otherwise
    # become the only physical transaction and survive a caller rollback.
    if not db.in_transaction():
        db.begin()
    if db.bind.dialect.name == "sqlite":
        connection = db.connection()
        raw_connection = connection.connection
        if not raw_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    locked_payments, locked_invoices = _lock_sync_rows(db, payload)
    sales_orders_by_id, sales_orders_by_no, sales_order_references = _sales_order_lookup(db, payload)
    invoices_by_id = {int(invoice.id): invoice for invoice in locked_invoices}
    invoices_by_no = {str(invoice.invoice_no): invoice for invoice in locked_invoices}
    invoices_by_external_id = {
        str(invoice.external_id): invoice
        for invoice in locked_invoices
        if invoice.external_source == SOURCE_1C and invoice.external_id
    }
    payments_by_external_id = {
        str(payment.external_id): payment
        for payment in locked_payments
        if payment.external_source == SOURCE_1C and payment.external_id
    }

    for i, row in enumerate(payload.invoices):
        try:
            with db.begin_nested():
                sales_order = _resolve_sales_order(
                    db, row.sales_order_id, row.sales_order_no,
                    by_id=sales_orders_by_id,
                    by_no=sales_orders_by_no,
                    reference_lookup=sales_order_references,
                )
                if not sales_order:
                    raise ValueError("sales order not found (provide sales_order_id or sales_order_no)")
                status = _validate_invoice_status(row.status)
                invoice = invoices_by_external_id.get(row.external_id)
                is_new = invoice is None
                previous_invoice_no = invoice.invoice_no if invoice is not None else None
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
                invoice.status = status
                db.flush()

            if previous_invoice_no and invoices_by_no.get(str(previous_invoice_no)) is invoice:
                invoices_by_no.pop(str(previous_invoice_no), None)
            invoices_by_id[int(invoice.id)] = invoice
            invoices_by_no[str(invoice.invoice_no)] = invoice
            invoices_by_external_id[str(invoice.external_id)] = invoice
            if is_new:
                summary["invoices_created"] += 1
            else:
                summary["invoices_updated"] += 1
        except Exception as e:
            summary["errors"].append({"type": "invoice", "index": i, "external_id": row.external_id, "error": str(e)})

    affected_invoice_ids: set[int] = set()
    for i, row in enumerate(payload.payments):
        try:
            with db.begin_nested():
                invoice = _resolve_invoice(
                    db, row.invoice_id, row.invoice_no, row.invoice_external_id,
                    by_id=invoices_by_id,
                    by_no=invoices_by_no,
                    by_external_id=invoices_by_external_id,
                )
                if not invoice:
                    raise ValueError("invoice not found (provide invoice_id, invoice_no, or invoice_external_id)")
                payment = payments_by_external_id.get(row.external_id)
                is_new = payment is None
                previous_invoice_id = payment.invoice_id if payment else None
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

                affected_invoice_ids.update(
                    int(invoice_id) for invoice_id in {invoice.id, previous_invoice_id} if invoice_id is not None
                )

            payments_by_external_id[str(payment.external_id)] = payment
            if is_new:
                summary["payments_created"] += 1
            else:
                summary["payments_updated"] += 1
        except Exception as e:
            summary["errors"].append({"type": "payment", "index": i, "external_id": row.external_id, "error": str(e)})

    if affected_invoice_ids:
        paid_totals = dict(
            db.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id.in_(sorted(affected_invoice_ids)))
            .group_by(Payment.invoice_id)
            .all()
        )
        # Preserve the existing private refresh hook as a synchronization
        # point for the PostgreSQL race tests; apply the preloaded totals to
        # every affected invoice below instead of recalculating per payment.
        affected_invoices = db.query(Invoice).filter(Invoice.id.in_(sorted(affected_invoice_ids))).all()
        if affected_invoices:
            _refresh_invoice_status(db, min(affected_invoices, key=lambda row: int(row.id)))
        for invoice in affected_invoices:
            total_paid = float(paid_totals.get(invoice.id, 0) or 0)
            amount = float(invoice.amount or 0)
            invoice.status = "paid" if total_paid >= amount else "partially_paid" if total_paid > 0 else "unpaid"

    return summary

