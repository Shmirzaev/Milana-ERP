from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_

from app.core.deps import DbSession, require_permissions
from app.models import (Customer, FinishedGoodsStock, Model, Package, Shipment, ShipmentPackage,
                        StockReservation, User, WarehousePackReservation)
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.numbering import next_shipment_no
from app.services.packaging_scope import require_package_access

router = APIRouter(prefix="/warehouse-reservations", tags=["warehouse"])
ACCESS = ("storage.packages", "storage.shipment", "*")


class ReservePacks(BaseModel):
    customer_id: int = Field(gt=0, le=2147483647)
    package_ids: list[int] = Field(min_length=1, max_length=50)
    notes: str | None = Field(None, max_length=1000)


class SelectedPacks(BaseModel):
    package_ids: list[int] = Field(min_length=1, max_length=50)


class ScanPack(BaseModel):
    code: str = Field(min_length=1, max_length=2048)


@router.post("/scan")
def resolve_reservation_pack(payload: ScanPack, db: DbSession,
                             current: User = Depends(require_permissions(*ACCESS))):
    from app.api.routes.packages import _package_for_receiving_scan
    package = _package_for_receiving_scan(db, payload.code.strip())
    if not package:
        raise HTTPException(404, "Package not found")
    require_package_access(current, package)
    # This read-only scan selects a pack. The reserve action locks and validates
    # its stock again so a concurrent sale/reservation cannot be overwritten.
    rows = db.query(FinishedGoodsStock).filter_by(package_id=package.id).all()
    if (package.status != "received_in_storage" or package.sales_order_id or
            package.stock_kind != "standard" or not rows or
            sum(row.quantity for row in rows) != package.total_quantity or
            any(row.quantity <= 0 or row.quantity != row.available_qty or row.reserved_qty or row.sold_qty
                or row.status != "available" or row.sales_order_id for row in rows) or
            _linked(db, [package.id]) or
            db.query(WarehousePackReservation.id).filter_by(package_id=package.id).first() or
            db.query(StockReservation.id).filter_by(package_id=package.id).first()):
        raise HTTPException(409, "Only complete available warehouse packs can be reserved")
    model = db.get(Model, package.model_id) if package.model_id else None
    return {"id": package.id, "package_no": package.package_no, "quantity": package.total_quantity,
            "model_code": model.code if model else "", "model_name": model.name if model else ""}


def _packages(db, current, ids):
    if any(value < 1 or value > 2147483647 for value in ids) or len(set(ids)) != len(ids):
        raise HTTPException(422, "Select distinct valid packs")
    packages = (db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id)
                .with_for_update().populate_existing().all())
    if len(packages) != len(ids):
        raise HTTPException(404, "Package not found")
    for package in packages:
        require_package_access(current, package)
    return packages


def _stocks(db, ids):
    rows = (db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids))
            .order_by(FinishedGoodsStock.id).with_for_update().populate_existing().all())
    by_package = {pid: [] for pid in ids}
    for row in rows:
        by_package[row.package_id].append(row)
    return by_package


def _linked(db, ids):
    return db.query(ShipmentPackage.id).join(Shipment).filter(
        ShipmentPackage.package_id.in_(ids), Shipment.status != "cancelled").first() is not None


def _release(db, current, packages, stocks):
    ids = [p.id for p in packages]
    holds = (db.query(WarehousePackReservation).filter(WarehousePackReservation.package_id.in_(ids))
             .order_by(WarehousePackReservation.package_id).with_for_update().populate_existing().all())
    by_package = {hold.package_id: hold for hold in holds}
    if len(holds) != len(packages) or _linked(db, ids):
        raise HTTPException(409, "Reservation changed or pack is attached to a shipment")
    if db.query(StockReservation.id).filter(StockReservation.package_id.in_(ids)).first():
        raise HTTPException(409, "Pack has another stock claim")
    for package in packages:
        rows = stocks[package.id]
        if (package.status != "reserved" or not rows or
                by_package[package.id].quantity != package.total_quantity or
                sum(row.quantity for row in rows) != package.total_quantity or
                any(row.sold_qty or row.available_qty or row.reserved_qty != row.quantity or
                    row.status != "reserved" for row in rows)):
            raise HTTPException(409, "Reserved pack stock changed; reload before releasing")
    for package in packages:
        for row in stocks[package.id]:
            row.available_qty = row.quantity
            row.reserved_qty = 0
            row.status = "available"
        package.status = "received_in_storage"
        hold = by_package[package.id]
        log_action(db, current, "release_customer_reservation", "Package", package.id,
                   old_value={"customer_id": hold.customer_id, "quantity": hold.quantity})
        db.delete(hold)
    return holds


@router.get("/customers")
def reservation_customers(db: DbSession, _: User = Depends(require_permissions(*ACCESS)),
                          q: str | None = Query(None, max_length=100)):
    query = db.query(Customer.id, Customer.name)
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(Customer.name.ilike(pattern, escape="\\"))
    return {"rows": [{"id": cid, "name": name} for cid, name in query.order_by(Customer.name, Customer.id).limit(50)]}


@router.get("")
def list_packs(db: DbSession, current: User = Depends(require_permissions(*ACCESS)),
               reserved: bool = True, customer_id: int | None = None,
               q: str | None = Query(None, max_length=100),
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=50)):
    from app.services.packaging_scope import packaging_department_scope
    from app.services.factory_scope import factory_for_department, user_is_super_admin
    totals = (db.query(FinishedGoodsStock.package_id.label("pid"),
                      func.sum(FinishedGoodsStock.available_qty).label("available"),
                      func.sum(FinishedGoodsStock.reserved_qty).label("reserved"),
                      func.sum(FinishedGoodsStock.sold_qty).label("sold"))
              .group_by(FinishedGoodsStock.package_id).subquery())
    query = (db.query(Package, WarehousePackReservation, Customer.name, Model.code, Model.name)
             .outerjoin(WarehousePackReservation, WarehousePackReservation.package_id == Package.id)
             .outerjoin(Customer, Customer.id == WarehousePackReservation.customer_id)
             .outerjoin(Model, Model.id == Package.model_id).join(totals, totals.c.pid == Package.id))
    if factory_for_department(getattr(getattr(current, "department", None), "code", None)) or user_is_super_admin(current):
        query = query.filter(Package.packaging_department_code == packaging_department_scope(current, None))
    if reserved:
        query = query.filter(WarehousePackReservation.id.isnot(None))
        if customer_id:
            query = query.filter(WarehousePackReservation.customer_id == customer_id)
    else:
        linked = db.query(ShipmentPackage.package_id).join(Shipment).filter(Shipment.status != "cancelled")
        query = query.filter(Package.status == "received_in_storage", Package.sales_order_id.is_(None),
                             Package.stock_kind == "standard", WarehousePackReservation.id.is_(None),
                             totals.c.available == Package.total_quantity, totals.c.reserved == 0,
                             totals.c.sold == 0, Package.id.notin_(linked))
    if q and q.strip():
        for word in q.strip().split():
            pattern = "%" + word.replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.filter(or_(*(column.ilike(pattern, escape="\\") for column in
                                      (Package.package_no, Package.barcode, Model.code, Model.name, Customer.name))))
    total = query.count()
    rows = [{"id": package.id, "package_no": package.package_no, "model_code": code,
             "model_name": name, "quantity": package.total_quantity,
             "customer_id": hold.customer_id if hold else None, "customer_name": customer,
             "notes": hold.notes if hold else None, "reserved_at": hold.reserved_at if hold else None}
            for package, hold, customer, code, name in query.order_by(Package.id.desc())
            .offset((page - 1) * page_size).limit(page_size)]
    return {"rows": rows, "total": total, "has_more": page * page_size < total}


@router.post("")
def reserve_packs(payload: ReservePacks, db: DbSession,
                  current: User = Depends(require_permissions(*ACCESS)),
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    fingerprint = payload.model_dump()
    replay = replay_idempotent_response(db, scope="warehouse-reservations.reserve", key=idempotency_key, payload=fingerprint)
    if replay is not None:
        return replay
    if not db.get(Customer, payload.customer_id):
        raise HTTPException(404, "Customer not found")
    packages = _packages(db, current, payload.package_ids)
    stocks = _stocks(db, payload.package_ids)
    if (_linked(db, payload.package_ids) or db.query(WarehousePackReservation.id).filter(
            WarehousePackReservation.package_id.in_(payload.package_ids)).first() or
            db.query(StockReservation.id).filter(StockReservation.package_id.in_(payload.package_ids)).first()):
        raise HTTPException(409, "A pack is already reserved or assigned to a shipment")
    for package in packages:
        rows = stocks[package.id]
        if (package.status != "received_in_storage" or package.sales_order_id or
                package.stock_kind != "standard" or not rows or
                sum(row.quantity for row in rows) != package.total_quantity or
                any(row.quantity <= 0 or row.quantity != row.available_qty or row.reserved_qty or row.sold_qty
                    or row.status != "available" or row.sales_order_id for row in rows)):
            raise HTTPException(409, "Only complete available warehouse packs can be reserved")
    for package in packages:
        for row in stocks[package.id]:
            row.reserved_qty = row.quantity
            row.available_qty = 0
            row.status = "reserved"
        package.status = "reserved"
        db.add(WarehousePackReservation(package_id=package.id, customer_id=payload.customer_id,
                                       quantity=package.total_quantity, reserved_by=current.id, notes=payload.notes))
        log_action(db, current, "reserve_for_customer", "Package", package.id,
                   new_value={"customer_id": payload.customer_id, "quantity": package.total_quantity, "notes": payload.notes})
    response = {"reserved": len(packages)}
    store_idempotent_response(db, scope="warehouse-reservations.reserve", key=idempotency_key,
                              payload=fingerprint, response=response, user=current)
    db.commit()
    return response


@router.post("/release")
def release_packs(payload: SelectedPacks, db: DbSession,
                  current: User = Depends(require_permissions(*ACCESS)),
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    fingerprint = payload.model_dump()
    replay = replay_idempotent_response(db, scope="warehouse-reservations.release", key=idempotency_key, payload=fingerprint)
    if replay is not None:
        return replay
    packages = _packages(db, current, payload.package_ids)
    _release(db, current, packages, _stocks(db, payload.package_ids))
    response = {"released": len(packages)}
    store_idempotent_response(db, scope="warehouse-reservations.release", key=idempotency_key,
                              payload=fingerprint, response=response, user=current)
    db.commit()
    return response


@router.post("/prepare-shipment")
def prepare_shipment(payload: SelectedPacks, db: DbSession,
                     current: User = Depends(require_permissions("storage.shipment", "*")),
                     idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    fingerprint = payload.model_dump()
    replay = replay_idempotent_response(db, scope="warehouse-reservations.shipment", key=idempotency_key, payload=fingerprint)
    if replay is not None:
        return replay
    packages = _packages(db, current, payload.package_ids)
    holds = _release(db, current, packages, _stocks(db, payload.package_ids))
    customers = {hold.customer_id for hold in holds}
    if len(customers) != 1:
        raise HTTPException(409, "Select reservations for one customer")
    shipment = Shipment(customer_id=customers.pop(), shipment_no=next_shipment_no(db),
                        status="created", dispatch_snapshot={"manual": True})
    db.add(shipment)
    db.flush()
    for package in packages:
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=package.total_quantity))
    log_action(db, current, "create_from_reservations", "Shipment", shipment.id,
               new_value={"package_ids": payload.package_ids, "customer_id": shipment.customer_id})
    response = {"id": shipment.id, "shipment_no": shipment.shipment_no}
    store_idempotent_response(db, scope="warehouse-reservations.shipment", key=idempotency_key,
                              payload=fingerprint, response=response, user=current)
    db.commit()
    return response
