from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.models import Package, Model, User
from app.schemas.tracking import PackageIn, PackageOut, PackageDetail
from app.services.packages import (
    create_package, receive_at_storage, reserve_package, ship_package, mark_delivered, mark_damaged,
)
from app.services.audit import log_action

router = APIRouter(prefix="/packages", tags=["packages"])


@router.get("", response_model=list[PackageOut])
def list_packages(db: DbSession, _: CurrentUser,
                  status: str | None = None, production_order_id: int | None = None,
                  page: int = 1, page_size: int = 100):
    qry = db.query(Package)
    if status: qry = qry.filter(Package.status == status)
    if production_order_id: qry = qry.filter(Package.production_order_id == production_order_id)
    return qry.order_by(Package.id.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.post("", response_model=PackageOut, status_code=201)
def create_pkg(payload: PackageIn, db: DbSession, current: User = Depends(require_permissions("packaging.packages", "*"))):
    pkg = create_package(
        db,
        production_order_id=payload.production_order_id,
        model_id=payload.model_id,
        color=payload.color,
        items=[i.model_dump() for i in payload.items],
        sales_order_id=payload.sales_order_id,
        brand_id=payload.brand_id,
        collection_id=payload.collection_id,
        package_type=payload.package_type,
        capacity=payload.capacity,
        warehouse_id=payload.warehouse_id,
        override_capacity=payload.override_capacity,
        is_admin=is_admin(current),
        user_id=current.id,
        notes=payload.notes,
    )
    log_action(db, current, "create", "Package", pkg.id, new_value={"package_no": pkg.package_no})
    db.commit(); db.refresh(pkg)
    return pkg


@router.get("/{pid}", response_model=PackageDetail)
def get_pkg(pid: int, db: DbSession, _: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    return p


@router.get("/barcode/{code}", response_model=PackageDetail)
def get_pkg_by_barcode(code: str, db: DbSession, _: CurrentUser):
    p = db.query(Package).filter((Package.barcode == code) | (Package.package_no == code)).first()
    if not p: raise HTTPException(404, "Package not found")
    return p


@router.post("/{pid}/receive-storage", response_model=PackageDetail)
def api_receive(pid: int, db: DbSession, current: User = Depends(require_permissions("storage.packages", "*")), warehouse_id: int | None = None):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    receive_at_storage(db, p, warehouse_id, current.id)
    log_action(db, current, "receive_storage", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.post("/{pid}/reserve", response_model=PackageDetail)
def api_reserve(pid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    reserve_package(db, p, current.id)
    log_action(db, current, "reserve", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.post("/{pid}/ship", response_model=PackageDetail)
def api_ship(pid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    ship_package(db, p, current.id)
    log_action(db, current, "ship", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.post("/{pid}/mark-delivered", response_model=PackageDetail)
def api_delivered(pid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    mark_delivered(db, p, current.id)
    log_action(db, current, "delivered", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.post("/{pid}/mark-damaged", response_model=PackageDetail)
def api_damaged(pid: int, db: DbSession, current: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    mark_damaged(db, p, current.id)
    log_action(db, current, "damaged", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.get("/{pid}/history")
def history(pid: int, db: DbSession, _: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    return [
        {"id": s.id, "scan_type": s.scan_type, "scanned_by": s.scanned_by, "scanned_at": s.scanned_at, "location": s.location}
        for s in p.scan_logs
    ]


@router.get("/{pid}/label", response_class=HTMLResponse)
def label(pid: int, db: DbSession, _: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    model = db.get(Model, p.model_id)
    sizes = "<br>".join(f"{it.size}: {it.quantity}" for it in p.items)
    qr = p.qr_code_url or ""
    return f"""<!doctype html>
<html><head><title>Package Label {p.package_no}</title>
<style>body{{font-family:Arial;margin:0;padding:8mm}} .label{{border:1px solid #000;padding:6mm;width:90mm}} .row{{display:flex;justify-content:space-between;font-size:10pt}} img{{max-width:32mm}} h2{{margin:0 0 4mm 0;font-size:14pt}}@media print{{body{{margin:0}}}}</style></head>
<body><div class=\"label\">
<h2>MILANA ERP</h2>
<div class=\"row\"><b>Package</b><span>{p.package_no}</span></div>
<div class=\"row\"><b>Model</b><span>{model.code if model else ''}</span></div>
<div class=\"row\"><b>Color</b><span>{p.color}</span></div>
<div class=\"row\"><b>Total Qty</b><span>{p.total_quantity}</span></div>
<div style=\"margin-top:3mm;font-size:9pt\"><b>Sizes:</b><br>{sizes}</div>
<div class=\"row\" style=\"margin-top:3mm\"><b>Barcode</b><span>{p.barcode}</span></div>
<div style=\"text-align:center;margin-top:4mm\"><img src=\"{qr}\" alt=\"QR\"/></div>
<button onclick=\"window.print()\">Print</button>
</div></body></html>"""
