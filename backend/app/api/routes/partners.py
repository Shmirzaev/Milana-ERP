from datetime import date

from fastapi import APIRouter, Depends, Header

from app.core.deps import (
    CUSTOMER_READ_PERMISSIONS,
    DbSession,
    SUPPLIER_READ_PERMISSIONS,
    require_permissions,
)
from app.libs.dto.catalog.party_input import PartyIn
from app.libs.dto.catalog.party_output import PartyOut
from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.libs.dto.sales.customer_order_output import CustomerOrderLedgerOut
from app.models.catalog import partners_service
from app.models.finance.customer_ledger_service import (
    list_customer_orders,
    list_customer_payments,
    record_customer_payment,
)
from app.schemas import User

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
    return partners_service.list_customers(_, db, q, created_from, created_to, page, page_size, include_total)


@router.post("/customers", response_model=PartyOut, status_code=201)
def create_customer(payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("sales.customers", "*"))):
    return partners_service.create_customer(current, db, payload)


@router.get("/customers/{cid}", response_model=PartyOut)
def get_customer(cid: int, db: DbSession, _: User = Depends(require_permissions(*CUSTOMER_READ_PERMISSIONS))):
    return partners_service.get_customer(_, db, cid)


@router.get("/customers/{cid}/orders", response_model=list[CustomerOrderLedgerOut])
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
    return partners_service.update_customer(current, db, cid, payload)


@router.delete("/customers/{cid}", status_code=204)
def delete_customer(cid: int, db: DbSession, current: User = Depends(require_permissions("sales.customers", "*"))):
    return partners_service.delete_customer(current, db, cid)


# ===== Suppliers =====
@router.get("/suppliers", response_model=list[PartyOut])
def list_suppliers(db: DbSession, _: User = Depends(require_permissions(*SUPPLIER_READ_PERMISSIONS))):
    return partners_service.list_suppliers(_, db)


@router.post("/suppliers", response_model=PartyOut, status_code=201)
def create_supplier(payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    return partners_service.create_supplier(current, db, payload)


@router.get("/suppliers/{sid}", response_model=PartyOut)
def get_supplier(sid: int, db: DbSession, _: User = Depends(require_permissions(*SUPPLIER_READ_PERMISSIONS))):
    return partners_service.get_supplier(_, db, sid)


@router.patch("/suppliers/{sid}", response_model=PartyOut)
def update_supplier(sid: int, payload: PartyIn, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    return partners_service.update_supplier(current, db, sid, payload)


@router.delete("/suppliers/{sid}", status_code=204)
def delete_supplier(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.suppliers", "*"))):
    return partners_service.delete_supplier(current, db, sid)
