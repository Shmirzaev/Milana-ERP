from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Shipment, ShipmentPackage, Package, SalesOrder, User, Model
from app.schemas.sales import ShipmentIn, ShipmentOut
from app.services.audit import log_action
from app.services.numbering import next_shipment_no
from app.services.packages import ship_package, mark_delivered
from app.services.workflow import ensure_invoice_for_delivered_shipment, notify_department

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=list[ShipmentOut])
def list_shipments(db: DbSession, _: CurrentUser):
    return db.query(Shipment).order_by(Shipment.id.desc()).all()


@router.get("/ready-packages")
def ready_packages(db: DbSession, _: CurrentUser, sales_order_id: int | None = None):
    qry = (
        db.query(Package, Model)
        .join(Model, Model.id == Package.model_id)
        .filter(Package.status.in_(["received_in_storage", "reserved"]))
    )
    if sales_order_id:
        qry = qry.filter(Package.sales_order_id == sales_order_id)
    rows = qry.order_by(Package.id.asc()).all()
    return [
        {
            "id": p.id,
            "package_no": p.package_no,
            "sales_order_id": p.sales_order_id,
            "model_id": p.model_id,
            "model_code": model.code if model else None,
            "color": p.color,
            "total_quantity": p.total_quantity,
            "status": p.status,
            "storage_cell": p.storage_cell,
            "storage_shelf": p.storage_shelf,
        }
        for p, model in rows
    ]


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
    if pkg.status not in ("received_in_storage", "reserved"):
        raise HTTPException(409, f"Package {pkg.package_no} is not ready to ship")
    exists = db.query(ShipmentPackage).filter(
        ShipmentPackage.shipment_id == sh.id, ShipmentPackage.package_id == pkg.id,
    ).first()
    if exists:
        raise HTTPException(409, "Package already attached to this shipment")
    db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
    log_action(db, current, "add_package", "Shipment", sh.id, new_value={"package_id": pkg.id})
    db.commit()
    return {"message": "added"}


@router.post("/{sid}/add-ready-packages")
def add_ready_packages(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    if not sh.sales_order_id:
        raise HTTPException(400, "Shipment has no sales_order_id")
    attached = {sp.package_id for sp in sh.packages}
    ready = db.query(Package).filter(
        Package.sales_order_id == sh.sales_order_id,
        Package.status.in_(["received_in_storage", "reserved"]),
    ).all()
    added = 0
    for p in ready:
        if p.id in attached:
            continue
        db.add(ShipmentPackage(shipment_id=sh.id, package_id=p.id, quantity=p.total_quantity))
        added += 1
    log_action(db, current, "add_ready_packages", "Shipment", sh.id, new_value={"added": added})
    db.commit()
    return {"added": added}


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
    inv = ensure_invoice_for_delivered_shipment(db, sales_order_id=sh.sales_order_id)
    if inv:
        notify_department(
            db,
            department_code="FIN",
            title="Shipment delivered - draft invoice created",
            message=f"Shipment {sh.shipment_no} delivered. Invoice {inv.invoice_no} prepared.",
            link="/finance",
            exclude_user_id=current.id,
        )
    log_action(db, current, "deliver", "Shipment", sh.id)
    db.commit(); db.refresh(sh)
    return sh
