from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Shipment, ShipmentPackage, Package, SalesOrder, User
from app.schemas.sales import ShipmentIn, ShipmentOut
from app.services.audit import log_action
from app.services.numbering import next_shipment_no
from app.services.packages import ship_package, mark_delivered

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=list[ShipmentOut])
def list_shipments(db: DbSession, _: CurrentUser):
    return db.query(Shipment).order_by(Shipment.id.desc()).all()


@router.post("", response_model=ShipmentOut, status_code=201)
def create_shipment(payload: ShipmentIn, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    if payload.sales_order_id and not db.get(SalesOrder, payload.sales_order_id):
        raise HTTPException(404, "Sales order not found")
    sh = Shipment(
        sales_order_id=payload.sales_order_id,
        customer_id=payload.customer_id,
        shipment_no=next_shipment_no(db),
        status="draft",
        notes=payload.notes,
    )
    db.add(sh); db.flush()
    log_action(db, current, "create", "Shipment", sh.id, new_value={"shipment_no": sh.shipment_no})
    db.commit(); db.refresh(sh)
    return sh


@router.patch("/{sid}", response_model=ShipmentOut)
def update_shipment(sid: int, payload: dict, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    for k, v in payload.items():
        if hasattr(sh, k): setattr(sh, k, v)
    log_action(db, current, "update", "Shipment", sh.id)
    db.commit(); db.refresh(sh)
    return sh


@router.post("/{sid}/add-package")
def add_package(sid: int, package_id: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    pkg = db.get(Package, package_id)
    if not pkg: raise HTTPException(404, "Package not found")
    db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
    log_action(db, current, "add_package", "Shipment", sh.id, new_value={"package_id": pkg.id})
    db.commit()
    return {"message": "added"}


@router.post("/{sid}/ship", response_model=ShipmentOut)
def ship_all(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    sh.status = "shipped"
    sh.shipped_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status in ("received_in_storage", "reserved"):
            ship_package(db, pkg, current.id)
    log_action(db, current, "ship", "Shipment", sh.id)
    db.commit(); db.refresh(sh)
    return sh


@router.post("/{sid}/deliver", response_model=ShipmentOut)
def deliver(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    sh.status = "delivered"
    sh.delivered_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status == "shipped":
            mark_delivered(db, pkg, current.id)
    log_action(db, current, "deliver", "Shipment", sh.id)
    db.commit(); db.refresh(sh)
    return sh
