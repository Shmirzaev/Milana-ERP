from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Customer, Supplier, User
from app.schemas.catalog import PartyIn, PartyOut
from app.services.audit import log_action

router = APIRouter(tags=["partners"])


# ===== Customers =====
@router.get("/customers", response_model=list[PartyOut])
def list_customers(db: DbSession, _: CurrentUser, q: str | None = None):
    qry = db.query(Customer)
    if q:
        qry = qry.filter(Customer.name.ilike(f"%{q}%"))
    return qry.order_by(Customer.id.desc()).all()


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
