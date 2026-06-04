from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Customer, Supplier, SalesOrder, Shipment, User, Invoice, Payment
from app.schemas.catalog import PartyIn, PartyOut
from app.services.audit import log_action

router = APIRouter(tags=["partners"])


# ===== Customers =====
@router.get("/customers")
def list_customers(
    db: DbSession,
    _: CurrentUser,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(Customer)
    if q:
        qry = qry.filter(Customer.name.ilike(f"%{q}%"))
    total = qry.count() if include_total else 0
    qry = qry.order_by(Customer.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [PartyOut.model_validate(c).model_dump() for c in qry.all()]
    if include_total:
        return {"rows": rows, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
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
def get_customer(cid: int, db: DbSession, _: CurrentUser):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@router.get("/customers/{cid}/orders")
def get_customer_orders(cid: int, db: DbSession, _: CurrentUser):
    if not db.get(Customer, cid):
        raise HTTPException(404, "Customer not found")
    rows = db.query(SalesOrder).filter(SalesOrder.customer_id == cid).order_by(SalesOrder.id.desc()).all()
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

    return [
        _serialize_customer_order(so, invoices_by_order[int(so.id)], payments_by_invoice)
        for so in rows
    ]


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
        paid_amount = 0.0
        for payment in payments:
            amount = float(payment.amount or 0)
            paid_amount += amount
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
@router.get("/suppliers", response_model=list[PartyOut])
def list_suppliers(db: DbSession, _: CurrentUser):
    return db.query(Supplier).order_by(Supplier.id.desc()).all()


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
def get_supplier(sid: int, db: DbSession, _: CurrentUser):
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
