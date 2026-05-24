from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Customer, Supplier, SalesOrder, Shipment, User
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
    return [
        {
            "id": so.id,
            "order_no": so.order_no,
            "date": so.created_at,
            "total": float(so.total_amount or 0),
            "status": so.status,
        }
        for so in rows
    ]


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
