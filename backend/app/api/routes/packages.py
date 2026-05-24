from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
import base64
import os

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.core.config import settings
from app.models import Package, Model, User
from app.schemas.tracking import (
    PackageIn,
    PackageBulkIn,
    PackageOut,
    PackageDetail,
    PackageReceiveStorageIn,
    PackageStoragePlacementIn,
)
from app.services.packages import (
    WAREHOUSE_MAP_LAYOUT,
    create_package,
    create_packages_bulk,
    receive_at_storage,
    reserve_package,
    ship_package,
    mark_delivered,
    mark_damaged,
    place_on_storage_map,
    format_storage_location,
)
from app.services.barcode import save_qr_image
from app.services.audit import log_action

router = APIRouter(prefix="/packages", tags=["packages"])


def _qr_data_uri_for_package(db: DbSession, pkg: Package) -> str:
    """Return a render-safe QR src for HTML labels (data URI).

    Label pages are opened via Blob URLs in the frontend, so relative image URLs
    like /storage/barcodes/... can fail to resolve. We embed QR as base64 PNG to
    keep printing reliable in all browsers.
    """
    qr_rel = (pkg.qr_code_url or "").strip()
    qr_path = ""
    if qr_rel.startswith("/storage/barcodes/"):
        fname = qr_rel.split("/storage/barcodes/", 1)[1]
        qr_path = os.path.join(settings.BARCODE_STORAGE_DIR, fname)

    if not qr_path or not os.path.isfile(qr_path):
        payload = f"PACKAGE:{pkg.package_no}|{pkg.barcode}"
        qr_rel = save_qr_image(payload, f"package_qr_{pkg.package_no}")
        if pkg.qr_code_url != qr_rel:
            pkg.qr_code_url = qr_rel
            db.add(pkg)
            db.commit()
            db.refresh(pkg)
        fname = qr_rel.split("/storage/barcodes/", 1)[1]
        qr_path = os.path.join(settings.BARCODE_STORAGE_DIR, fname)

    with open(qr_path, "rb") as fh:
        png = fh.read()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


@router.get("")
def list_packages(db: DbSession, _: CurrentUser,
                  status: str | None = None, production_order_id: int | None = None,
                  page: int = 1, page_size: int = 50, include_total: bool = False):
    qry = db.query(Package)
    if status: qry = qry.filter(Package.status == status)
    if production_order_id: qry = qry.filter(Package.production_order_id == production_order_id)
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 500))
    rows = qry.order_by(Package.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size).all()
    out = [PackageOut.model_validate(p).model_dump() for p in rows]
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out


@router.post("", response_model=PackageOut, status_code=201)
def create_pkg(payload: PackageIn, db: DbSession, current: User = Depends(require_permissions("packaging.packages", "*"))):
    pkg = create_package(
        db,
        production_order_id=payload.production_order_id,
        production_batch_id=payload.production_batch_id,
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


@router.post("/bulk")
def create_pkg_bulk(payload: PackageBulkIn, db: DbSession, current: User = Depends(require_permissions("packaging.packages", "*"))):
    pkgs = create_packages_bulk(
        db,
        count=payload.count,
        production_order_id=payload.production_order_id,
        production_batch_id=payload.production_batch_id,
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
    for p in pkgs:
        log_action(db, current, "create", "Package", p.id, new_value={"package_no": p.package_no, "mode": "bulk"})
    db.commit()
    return {
        "count": len(pkgs),
        "package_ids": [p.id for p in pkgs],
        "package_nos": [p.package_no for p in pkgs],
    }


@router.get("/storage-map")
def storage_map(
    db: DbSession,
    _: CurrentUser,
    model_query: str | None = None,
):
    query = (
        db.query(Package, Model)
        .join(Model, Model.id == Package.model_id)
        .filter(
            Package.storage_cell.isnot(None),
            Package.status.in_(["packed", "received_in_storage", "reserved"]),
        )
        .order_by(Package.storage_cell.asc(), Package.storage_shelf.asc(), Package.id.desc())
    )

    q = (model_query or "").strip().lower()
    placements: list[dict] = []
    matches: list[dict] = []
    by_cell: dict[str, list[dict]] = {}
    for pkg, model in query.all():
        model_code = model.code if model else None
        model_name = model.name if model else None
        fields = [
            model_code or "",
            model_name or "",
            pkg.package_no or "",
            pkg.barcode or "",
        ]
        matched = bool(q) and any(q in f.lower() for f in fields)
        row = {
            "id": pkg.id,
            "package_no": pkg.package_no,
            "barcode": pkg.barcode,
            "model_id": pkg.model_id,
            "model_code": model_code,
            "model_name": model_name,
            "color": pkg.color,
            "total_quantity": pkg.total_quantity,
            "status": pkg.status,
            "storage_cell": pkg.storage_cell,
            "storage_shelf": pkg.storage_shelf,
            "storage_placed_at": pkg.storage_placed_at,
            "location": format_storage_location(pkg.storage_cell, pkg.storage_shelf),
            "matched": matched,
        }
        placements.append(row)
        if matched:
            matches.append(row)
        if pkg.storage_cell:
            by_cell.setdefault(pkg.storage_cell, []).append(row)

    cells: list[dict] = []
    for zone, size in WAREHOUSE_MAP_LAYOUT:
        for idx in range(1, size + 1):
            code = f"{zone}-{idx:02d}"
            packs = by_cell.get(code, [])
            count = len(packs)
            matched_count = sum(1 for p in packs if p["matched"])
            if count == 0:
                status = "free"
            elif count == 1:
                status = "partial"
            else:
                status = "full"
            cells.append(
                {
                    "code": code,
                    "zone": zone,
                    "count": count,
                    "status": status,
                    "matched_count": matched_count,
                    "package_nos": [p["package_no"] for p in packs],
                    "model_codes": [p["model_code"] for p in packs if p.get("model_code")],
                }
            )

    return {
        "query": model_query or "",
        "summary": {
            "cells_total": len(cells),
            "cells_occupied": sum(1 for c in cells if c["count"] > 0),
            "packages_on_map": len(placements),
            "matched_packages": len(matches),
        },
        "zones": [{"id": zone, "size": size} for zone, size in WAREHOUSE_MAP_LAYOUT],
        "cells": cells,
        "placements": placements,
        "matches": matches,
    }


@router.get("/storage-map/find")
def find_on_storage_map(
    db: DbSession,
    _: CurrentUser,
    q: str,
):
    needle = q.strip()
    if not needle:
        raise HTTPException(400, "q is required")
    like = f"%{needle}%"
    rows = (
        db.query(Package, Model)
        .join(Model, Model.id == Package.model_id)
        .filter(
            Package.storage_cell.isnot(None),
            Package.status.in_(["packed", "received_in_storage", "reserved"]),
            or_(
                Model.code.ilike(like),
                Model.name.ilike(like),
                Package.package_no.ilike(like),
                Package.barcode.ilike(like),
            ),
        )
        .order_by(Package.storage_cell.asc(), Package.storage_shelf.asc(), Package.id.desc())
        .all()
    )
    return [
        {
            "id": pkg.id,
            "package_no": pkg.package_no,
            "barcode": pkg.barcode,
            "model_id": pkg.model_id,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "color": pkg.color,
            "total_quantity": pkg.total_quantity,
            "status": pkg.status,
            "storage_cell": pkg.storage_cell,
            "storage_shelf": pkg.storage_shelf,
            "location": format_storage_location(pkg.storage_cell, pkg.storage_shelf),
        }
        for pkg, model in rows
    ]


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
def api_receive(
    pid: int,
    db: DbSession,
    payload: PackageReceiveStorageIn | None = None,
    warehouse_id: int | None = None,
    current: User = Depends(require_permissions("storage.packages", "*")),
):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    selected_warehouse_id = warehouse_id
    if payload and payload.warehouse_id is not None:
        selected_warehouse_id = payload.warehouse_id
    receive_at_storage(
        db,
        p,
        selected_warehouse_id,
        current.id,
        storage_cell=payload.storage_cell if payload else None,
        storage_shelf=payload.storage_shelf if payload else None,
    )
    log_action(db, current, "receive_storage", "Package", p.id)
    db.commit(); db.refresh(p)
    return p


@router.post("/{pid}/place-on-map", response_model=PackageDetail)
def api_place_on_map(
    pid: int,
    payload: PackageStoragePlacementIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "storage.shipment", "*")),
):
    p = db.get(Package, pid)
    if not p:
        raise HTTPException(404, "Package not found")
    place_on_storage_map(
        db,
        p,
        storage_cell=payload.storage_cell,
        storage_shelf=payload.storage_shelf,
        user_id=current.id,
    )
    log_action(
        db,
        current,
        "place_storage_map",
        "Package",
        p.id,
        new_value={"storage_cell": p.storage_cell, "storage_shelf": p.storage_shelf},
    )
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
def api_damaged(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "storage.shipment", "*")),
):
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
    qr = _qr_data_uri_for_package(db, p)
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


@router.get("/label-sheet/by-ids", response_class=HTMLResponse)
def label_sheet(ids: str, db: DbSession, _: CurrentUser):
    raw_ids = [s.strip() for s in (ids or "").split(",") if s.strip()]
    try:
        parsed_ids = [int(v) for v in raw_ids]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    if not parsed_ids:
        raise HTTPException(400, "Provide at least one package id")
    rows = (
        db.query(Package)
        .options(selectinload(Package.items))
        .filter(Package.id.in_(parsed_ids))
        .order_by(Package.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "No packages found")

    cards = []
    for p in rows:
        model = db.get(Model, p.model_id)
        qr = _qr_data_uri_for_package(db, p)
        sizes = "<br>".join(f"{it.size}: {it.quantity}" for it in p.items)
        cards.append(
            f"""
            <div class='label'>
              <h2>MILANA ERP</h2>
              <div class='row'><b>Package</b><span>{p.package_no}</span></div>
              <div class='row'><b>Model</b><span>{model.code if model else ''}</span></div>
              <div class='row'><b>Color</b><span>{p.color}</span></div>
              <div class='row'><b>Total Qty</b><span>{p.total_quantity}</span></div>
              <div style='margin-top:2mm;font-size:9pt'><b>Sizes:</b><br>{sizes}</div>
              <div class='row' style='margin-top:2mm'><b>Barcode</b><span>{p.barcode}</span></div>
              <div style='text-align:center;margin-top:3mm'><img src='{qr}' alt='QR'/></div>
            </div>
            """
        )
    return f"""<!doctype html>
<html><head><title>Package Label Sheet</title>
<style>
body{{font-family:Arial;margin:0;padding:6mm}}
.sheet{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6mm}}
.label{{border:1px solid #000;padding:5mm;min-height:56mm}}
.row{{display:flex;justify-content:space-between;font-size:10pt}}
img{{max-width:28mm}}
h2{{margin:0 0 3mm 0;font-size:13pt}}
@media print{{button{{display:none}} body{{padding:0}} .sheet{{gap:4mm}}}}
</style></head>
<body>
<div class='sheet'>{''.join(cards)}</div>
<button onclick="window.print()" style="margin-top:6mm">Print</button>
</body></html>"""
