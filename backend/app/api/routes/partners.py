from datetime import date

from fastapi import APIRouter, HTTPException, Depends, Header

from app.core.dt import date_filter_bounds
from app.core.deps import (
    CUSTOMER_READ_PERMISSIONS,
    DbSession,
    SUPPLIER_READ_PERMISSIONS,
    require_permissions,
)
from app.schemas import (
    Customer,
    PurchaseOrder,
    PurchaseRequestLine,
    SalesOrder,
    Shipment,
    StockBatch,
    Supplier,
    User,
)
from app.libs.dto.catalog.catalog import PartyIn, PartyOut
from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.models.audit_service import log_action
from app.models.finance.customer_ledger_service import (
    list_customer_orders,
    list_customer_payments,
    record_customer_payment,
)

router = APIRouter(tags=["partners"])


# ===== Customers =====
@router.get("/customers")
def list_customers(
    db: DbSession,
    _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS)),
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
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
def get_customer(cid: int, db: DbSession, _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS))):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@router.get("/customers/{cid}/orders")
def get_customer_orders(cid: int, db: DbSession, _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS))):
    return list_customer_orders(db, cid)


@router.get("/customers/{cid}/payments")
def get_customer_payments(cid: int, db: DbSession, _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS))):
    return list_customer_payments(db, cid)


@router.post("/customers/{cid}/payments", status_code=201)
def create_customer_payment(
    cid: int,
    payload: CustomerPaymentIn,
    db: DbSession,
    current: User = Depends(require_permissions("finance.payment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return record_customer_payment(db, cid, payload, current, idempotency_key)


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
def list_suppliers(db: DbSession, _: User = Depends(require_permissions(*SUPPLIER_READ_PERMISSIONS))):
    return db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.id.desc()).all()


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
