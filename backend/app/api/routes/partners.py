from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_

from app.core.dt import date_filter_bounds
from app.core.deps import (
    CUSTOMER_READ_PERMISSIONS,
    DbSession,
    SUPPLIER_READ_PERMISSIONS,
    require_permissions,
)
from app.models import (
    Customer,
    Invoice,
    Payment,
    PurchaseOrder,
    PurchaseRequestLine,
    SalesOrder,
    Shipment,
    StockBatch,
    Supplier,
    User,
)
from app.schemas.catalog import PartyIn, PartyOut
from app.schemas.partners import (
    CustomerOrderHistoryOut,
    CustomerOrderHistoryPageOut,
    CustomerPageOut,
    CustomerPaymentHistoryOut,
    CustomerPaymentHistoryPageOut,
    SupplierPageOut,
)
from app.services.audit import log_action
from app.services.numbering import next_invoice_no
from app.services.payments import create_customer_advance_payment, create_invoice_payment, invoice_paid_total
from app.services.idempotency import replay_idempotent_response, store_idempotent_response

router = APIRouter(tags=["partners"])


class CustomerPaymentIn(BaseModel):
    sales_order_id: int | None = None
    amount: float = Field(
        ge=0.01,
        le=999_999_999_999.99,
        multiple_of=0.01,
        allow_inf_nan=False,
    )
    paid_at: datetime | None = None
    payment_method: str | None = None
    notes: str | None = None


# ===== Customers =====
@router.get("/customers", response_model=list[PartyOut] | CustomerPageOut)
def list_customers(
    db: DbSession,
    _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS)),
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int | None = None,
    page_size: int | None = None,
    include_total: bool = False,
):
    qry = db.query(Customer)
    if q:
        qry = qry.filter(Customer.name.ilike(f"%{q}%"))
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(Customer.created_at >= start)
    if end:
        qry = qry.filter(Customer.created_at <= end)
    paginated = include_total or page is not None or page_size is not None
    if include_total:
        # Keep the historical include_total behavior, including clamping.
        effective_page = max(1, page or 1)
        effective_page_size = max(1, min(page_size or 50, 500))
    else:
        effective_page = page or 1
        effective_page_size = page_size or 50
        if effective_page < 1 or effective_page_size < 1 or effective_page_size > 500:
            raise HTTPException(422, "page must be >= 1 and page_size must be between 1 and 500")
    total = qry.count() if paginated else 0
    qry = qry.order_by(Customer.id.desc())
    if paginated:
        qry = qry.offset((effective_page - 1) * effective_page_size).limit(effective_page_size)
    rows = [PartyOut.model_validate(c).model_dump() for c in qry.all()]
    if paginated:
        return {
            "rows": rows,
            "total": total,
            "page": effective_page,
            "page_size": effective_page_size,
        }
    return rows


@router.post("/customers", response_model=PartyOut, status_code=201)
def create_customer(payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("sales.customers", "*"))):
    c = Customer(**payload.model_dump())
    db.add(c)
    db.flush()
    log_action(db, current, "create", "Customer", c.id)
    db.commit()
    db.refresh(c)
    return c


@router.get("/customers/{cid}", response_model=PartyOut)
def get_customer(cid: int, db: DbSession, _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS))):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@router.get(
    "/customers/{cid}/orders",
    response_model=list[CustomerOrderHistoryOut] | CustomerOrderHistoryPageOut,
)
def get_customer_orders(
    cid: int,
    db: DbSession,
    _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS)),
    status: str | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    query = db.query(SalesOrder).filter(SalesOrder.customer_id == cid)
    if status:
        query = query.filter(SalesOrder.status == status)
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = query.order_by(None).count()
    query = query.order_by(SalesOrder.id.desc())
    if total is not None:
        query = query.offset((page - 1) * page_size).limit(page_size)
    rows = query.all()
    order_ids = [int(so.id) for so in rows]
    invoices_by_order: dict[int, list[Invoice]] = defaultdict(list)
    payments_by_invoice: dict[int, list[Payment]] = defaultdict(list)

    if order_ids:
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

    payloads = [
        _serialize_customer_order(so, invoices_by_order[int(so.id)], payments_by_invoice)
        for so in rows
    ]
    if total is None:
        return payloads
    return {
        "rows": payloads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.get(
    "/customers/{cid}/payments",
    response_model=list[CustomerPaymentHistoryOut] | CustomerPaymentHistoryPageOut,
)
def get_customer_payments(
    cid: int,
    db: DbSession,
    _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS)),
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    query = (
        db.query(Payment, Invoice, SalesOrder)
        .outerjoin(Invoice, Invoice.id == Payment.invoice_id)
        .outerjoin(SalesOrder, SalesOrder.id == Invoice.sales_order_id)
        .filter(or_(SalesOrder.customer_id == cid, Payment.customer_id == cid))
    )
    ordered_query = query.order_by(Payment.id.desc())
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = query.order_by(None).count()
        ordered_query = ordered_query.offset((page - 1) * page_size).limit(page_size)
    else:
        ordered_query = ordered_query.limit(limit)
    rows = ordered_query.all()
    payloads = [
        _serialize_customer_payment(payment, invoice, so)
        for payment, invoice, so in rows
    ]
    if total is None:
        return payloads
    return {
        "rows": payloads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.post("/customers/{cid}/payments", status_code=201)
def create_customer_payment(
    cid: int,
    payload: CustomerPaymentIn,
    db: DbSession,
    current: User = Depends(require_permissions("finance.payment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"customer_id": cid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(db, user=current, scope="customers.payments", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    if payload.amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero")

    sales_order = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if payload.sales_order_id and (not sales_order or int(sales_order.customer_id or 0) != cid):
        raise HTTPException(404, "Sales order not found for this customer")

    payment = None
    invoice = None
    amount_remaining = float(payload.amount)

    if sales_order:
        invoice = _find_payable_invoice(db, sales_order)
        if not invoice and not _order_has_invoices(db, sales_order):
            invoice = Invoice(
                sales_order_id=sales_order.id,
                invoice_no=next_invoice_no(db),
                amount=float(sales_order.total_amount or 0),
                status="unpaid",
                issued_at=datetime.now(timezone.utc),
            )
            db.add(invoice)
            db.flush()

        if invoice:
            invoice_balance = max(float(invoice.amount or 0) - invoice_paid_total(db, int(invoice.id)), 0)
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
                amount_remaining = round(amount_remaining - invoice_amount, 2)

    if amount_remaining >= 0.01:
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
        current,
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
        user=current,
        status_code=201,
    )
    db.commit()
    db.refresh(payment)
    if invoice:
        db.refresh(invoice)
    return response


def _find_payable_invoice(db: DbSession, sales_order: SalesOrder) -> Invoice | None:
    # Keep invoice selection and the invoice/advance split under the same lock
    # used by direct finance payments, including when these rows are cached.
    invoices = (
        db.query(Invoice)
        .filter(Invoice.sales_order_id == sales_order.id)
        .order_by(Invoice.id.asc())
        .populate_existing()
        .with_for_update(of=Invoice)
        .all()
    )
    # All candidate invoices are locked above before reading their totals.
    # Batch the sums without loading each payment or changing allocation order.
    paid_by_invoice = {}
    invoice_ids = [int(invoice.id) for invoice in invoices]
    for start in range(0, len(invoice_ids), 400):
        paid_by_invoice.update(
            db.query(Payment.invoice_id, func.sum(Payment.amount))
            .filter(Payment.invoice_id.in_(invoice_ids[start:start + 400]))
            .group_by(Payment.invoice_id)
            .all()
        )
    for invoice in invoices:
        balance_due = max(float(invoice.amount or 0) - float(paid_by_invoice.get(int(invoice.id)) or 0), 0)
        if balance_due > 0.01:
            return invoice
    return None


def _order_has_invoices(db: DbSession, sales_order: SalesOrder) -> bool:
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
) -> dict:
    invoice_payloads: list[dict] = []
    invoice_total = 0.0
    paid_total = 0.0
    last_payment_at = None

    for inv in invoices:
        payments = payments_by_invoice.get(int(inv.id), [])
        payment_payloads = []
        raw_paid_amount = 0.0
        for payment in payments:
            amount = float(payment.amount or 0)
            raw_paid_amount += amount
            if payment.paid_at and (last_payment_at is None or payment.paid_at > last_payment_at):
                last_payment_at = payment.paid_at
            payment_payloads.append(
                {
                    "id": payment.id,
                    "amount": amount,
                    "payment_method": payment.payment_method,
                    "paid_at": payment.paid_at,
                    "notes": payment.notes,
                }
            )

        amount = float(inv.amount or 0)
        paid_amount = min(raw_paid_amount, amount)
        advance_amount = max(raw_paid_amount - amount, 0)
        invoice_total += amount
        paid_total += paid_amount
        invoice_payloads.append(
            {
                "id": inv.id,
                "invoice_no": inv.invoice_no,
                "amount": amount,
                "status": inv.status,
                "issued_at": inv.issued_at,
                "due_date": inv.due_date,
                "paid_amount": round(paid_amount, 2),
                "raw_paid_amount": round(raw_paid_amount, 2),
                "advance_amount": round(advance_amount, 2),
                "balance_due": round(max(amount - paid_amount, 0), 2),
                "payments": payment_payloads,
            }
        )

    balance_due = max((invoice_total if invoices else float(so.total_amount or 0)) - paid_total, 0)

    def payment_status() -> str:
        if not invoices:
            return "no_invoice"
        if invoice_total <= 0 or paid_total >= invoice_total - 0.01:
            return "paid"
        if paid_total > 0.01:
            return "partial"
        if any(str(inv.status or "").lower() in {"partial", "partially_paid"} for inv in invoices):
            return "partial"
        if all(str(inv.status or "").lower() == "paid" for inv in invoices):
            return "paid"
        return "unpaid"

    return {
        "id": so.id,
        "order_no": so.order_no,
        "date": so.created_at,
        "total": float(so.total_amount or 0),
        "status": so.status,
        "invoice_total": round(invoice_total, 2),
        "paid_total": round(paid_total, 2),
        "balance_due": round(balance_due, 2),
        "payment_status": payment_status(),
        "last_payment_at": last_payment_at,
        "invoices": invoice_payloads,
    }


@router.patch("/customers/{cid}", response_model=PartyOut)
def update_customer(cid: int, payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("sales.customers", "*"))):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    log_action(db, current, "update", "Customer", c.id)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/customers/{cid}", status_code=204)
def delete_customer(cid: int, db: DbSession, current: User = Depends(require_permissions("sales.customers", "*"))):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    if db.query(SalesOrder).filter(SalesOrder.customer_id == cid).first():
        raise HTTPException(409, "Customer is linked to sales orders")
    if db.query(Shipment).filter(Shipment.customer_id == cid).first():
        raise HTTPException(409, "Customer is linked to shipments")
    db.delete(c)
    log_action(db, current, "delete", "Customer", cid, new_value={"name": c.name})
    db.commit()


# ===== Suppliers =====
@router.get("/suppliers", response_model=list[PartyOut] | SupplierPageOut)
def list_suppliers(
    db: DbSession,
    _: User = Depends(require_permissions(*SUPPLIER_READ_PERMISSIONS)),
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    query = db.query(Supplier).filter(Supplier.is_active.is_(True))
    ordered_query = query.order_by(Supplier.id.desc())
    if page is None and page_size is None:
        return ordered_query.all()

    page = page or 1
    page_size = page_size or 50
    total = query.count()
    rows = ordered_query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.post("/suppliers", response_model=PartyOut, status_code=201)
def create_supplier(payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    s = Supplier(**payload.model_dump())
    db.add(s)
    db.flush()
    log_action(db, current, "create", "Supplier", s.id)
    db.commit()
    db.refresh(s)
    return s


@router.get("/suppliers/{sid}", response_model=PartyOut)
def get_supplier(sid: int, db: DbSession, _: User = Depends(require_permissions(*SUPPLIER_READ_PERMISSIONS))):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found")
    return s


@router.patch("/suppliers/{sid}", response_model=PartyOut)
def update_supplier(sid: int, payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    log_action(db, current, "update", "Supplier", s.id)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/suppliers/{sid}", status_code=204)
def delete_supplier(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found")
    linked = (
        db.query(StockBatch.id).filter(StockBatch.supplier_id == sid).first()
        or db.query(PurchaseRequestLine.id).filter(PurchaseRequestLine.preferred_supplier_id == sid).first()
        or db.query(PurchaseOrder.id).filter(PurchaseOrder.supplier_id == sid).first()
    )
    if linked:
        raise HTTPException(409, "Supplier is linked to stock or purchasing records and cannot be deleted")
    db.delete(s)
    log_action(db, current, "delete", "Supplier", sid, new_value={"name": s.name})
    db.commit()
