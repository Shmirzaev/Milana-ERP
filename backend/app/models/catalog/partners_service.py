"""Customer and supplier reference data.

Contract for the partner reference operations:
* input: a partner id, a validated `PartyIn` and the acting user
* output: the serialized customer or supplier
* refusals: 404 "Customer not found", 404 "Supplier not found" and 409 when the
  partner is still linked to orders, shipments, stock or purchasing records
* records: `customers` and `suppliers` rows plus the audit rows
* transaction owner: every operation below
"""

from datetime import date
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.core.dt import date_filter_bounds
from app.libs.dto.catalog.party_input import PartyIn
from app.libs.dto.catalog.party_output import PartyOut
from app.libs.types.catalog import CustomerUpdateCommand
from app.models.audit_service import log_action
from app.schemas import Customer, PurchaseOrder, PurchaseRequestLine, SalesOrder, Shipment, StockBatch, Supplier, User
from app.schemas.catalog.partners_persistence import apply_customer_update, insert_customer, insert_supplier


def list_customers(
    current: User,
    db: Session,
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


def create_customer(
    current: User,
    db: Session,
    payload: PartyIn,
):
    c = insert_customer(db, **payload.model_dump())
    log_action(db, current, "create", "Customer", c.id)
    db.commit()
    db.refresh(c)
    return c


def get_customer(
    current: User,
    db: Session,
    cid: int,
):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


def update_customer(
    current: User,
    db: Session,
    cid: int,
    payload: PartyIn,
):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    fields: CustomerUpdateCommand = {"name": payload.name}
    if "phone" in payload.model_fields_set:
        fields["phone"] = payload.phone
    if "email" in payload.model_fields_set:
        fields["email"] = payload.email
    if "address" in payload.model_fields_set:
        fields["address"] = payload.address
    if "notes" in payload.model_fields_set:
        fields["notes"] = payload.notes
    apply_customer_update(db, c, fields)
    log_action(db, current, "update", "Customer", c.id)
    db.commit()
    db.refresh(c)
    return c


def delete_customer(
    current: User,
    db: Session,
    cid: int,
):
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


def list_suppliers(
    current: User,
    db: Session,
):
    return db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.id.desc()).all()


def create_supplier(
    current: User,
    db: Session,
    payload: PartyIn,
):
    s = insert_supplier(db, **payload.model_dump())
    log_action(db, current, "create", "Supplier", s.id)
    db.commit()
    db.refresh(s)
    return s


def get_supplier(
    current: User,
    db: Session,
    sid: int,
):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found")
    return s


def update_supplier(
    current: User,
    db: Session,
    sid: int,
    payload: PartyIn,
):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    log_action(db, current, "update", "Supplier", s.id)
    db.commit()
    db.refresh(s)
    return s


def delete_supplier(
    current: User,
    db: Session,
    sid: int,
):
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
