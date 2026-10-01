"""Warehouse rejects unreceived packages; Packaging corrects and issues fresh labels."""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.models import Package, PackagePrintRun, PackagePrintRunMember, PackageChangeRequest, PackageScanLog, ProductionOrder
from app.services.audit import log_action
from app.services.barcode import generate_barcode_value
from app.services.packaging_scope import packaging_department_scope
from app.services.package_workflows import active_members, contents, create_run, run_payload
from app.services.packages import (
    _ensure_package_can_change, _apply_package_edit_request, normalize_package_edit_payload,
    package_snapshot, _require_warehouse_package,
)
from app.services.workflow import notify_department


def return_packages(db, current, payload):
    ids = sorted(set(payload.package_ids))
    members = active_members(db).filter(PackagePrintRunMember.package_id.in_(ids)).all()
    run_ids = sorted({member.run_id for member in members})
    runs = db.query(PackagePrintRun).filter(PackagePrintRun.id.in_(run_ids)).order_by(PackagePrintRun.id).with_for_update().populate_existing().all()
    if any(run.received_at or run.returned_at for run in runs):
        raise HTTPException(409, "Only unreceived packages can be returned to Packaging")
    if any(not set(run.package_ids).issubset(ids) for run in runs):
        raise HTTPException(409, "Select every package in the print run before returning it to Packaging")
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
    if len(packages) != len(ids):
        raise HTTPException(404, "Package not found")
    for pkg in packages:
        _require_warehouse_package(db, pkg)
        if pkg.status != "packed" or not pkg.production_order_id or pkg.manual_receipt_id or pkg.legacy_receipt_id:
            raise HTTPException(409, "Only production packages awaiting warehouse receipt can be returned")
        # Temporarily ignore only the active print membership, whose manifest is
        # retired below. Every reservation, shipment and stock guard still applies.
        from app.models import FinishedGoodsStock, ShipmentPackage, StockReservation
        if (db.query(StockReservation.id).filter_by(package_id=pkg.id).first()
                or db.query(ShipmentPackage.id).filter_by(package_id=pkg.id).first()
                or db.query(PackageChangeRequest.id).filter_by(package_id=pkg.id, status="pending").first()):
            raise HTTPException(409, "Package has a reservation, shipment or pending correction")
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=pkg.id).with_for_update().all()
        if any(row.reserved_qty or row.sold_qty or row.available_qty != row.quantity for row in stocks):
            raise HTTPException(409, "Package stock is reserved, sold or inconsistent")
    # Unprinted packages also receive an immutable pre-correction manifest.
    unprinted = [pkg for pkg in packages if pkg.id not in {member.package_id for member in members}]
    for owner in sorted({pkg.packaging_department_code for pkg in unprinted}):
        runs.append(create_run(db, current, [pkg for pkg in unprinted if pkg.packaging_department_code == owner]))
    now = datetime.now(timezone.utc)
    for run in runs:
        run.returned_at, run.returned_by, run.return_reason = now, current.id, payload.reason
        log_action(db, current, "return_to_packaging", "PackagePrintRun", run.id,
                   new_value={"package_ids": run.package_ids, "reason": payload.reason})
    for pkg in packages:
        pkg.status = "returned_to_packaging"
        pkg.storage_cell = pkg.storage_shelf = pkg.storage_placed_at = None
        db.add(PackageScanLog(package_id=pkg.id, scanned_by=current.id, scan_type="returned_to_packaging"))
    for owner in sorted({pkg.packaging_department_code for pkg in packages}):
        notify_department(db, department_code=owner, title="Packages returned for correction",
                          message=f"{', '.join(p.package_no for p in packages if p.packaging_department_code == owner)}: {payload.reason}",
                          link=f"/packages?packaging_department={owner}")
    db.flush()
    return {"count": len(packages), "package_ids": ids}


def correct_returned_package(db, current, pid, payload):
    identity = db.query(Package.production_order_id).filter_by(id=pid).scalar()
    if identity:
        db.query(ProductionOrder).filter_by(id=identity).with_for_update().first()
    pkg = db.query(Package).filter_by(id=pid).with_for_update().populate_existing().first()
    if not pkg:
        raise HTTPException(404, "Package not found")
    packaging_department_scope(current, pkg.packaging_department_code)
    if pkg.status != "returned_to_packaging":
        raise HTTPException(409, "Package is no longer awaiting Packaging correction")
    _ensure_package_can_change(db, pkg)
    if payload.request_type != "edit":
        raise HTTPException(400, "Returned package correction must be an edit")
    request = PackageChangeRequest(package_id=pkg.id, package_no=pkg.package_no, request_type="edit",
                                   status="pending", before_json=package_snapshot(pkg),
                                   payload_json=normalize_package_edit_payload(db, pkg, payload.payload.model_dump(exclude_unset=True) if payload.payload else None),
                                   reason=payload.reason, requested_by=current.id)
    db.add(request); db.flush()
    pkg = _apply_package_edit_request(db, request, current.id)
    request.status = "approved"
    request.reviewed_by = current.id
    request.reviewed_at = datetime.now(timezone.utc)
    request.decision_notes = "Packaging corrected a warehouse return"
    # Force a fresh physical QR. Old print manifests keep the prior barcode.
    db.expire(pkg, ["items", "batch_allocations"])
    pkg.barcode = generate_barcode_value("PKG")
    pkg.qr_code_url = None
    log_action(db, current, "correct_returned_package", "Package", pkg.id,
               old_value=request.before_json, new_value=contents(pkg))
    return {"id": pkg.id, "package_no": pkg.package_no}


def resend_packages(db, current, payload):
    ids = sorted(set(payload.package_ids))
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
    if len(packages) != len(ids):
        raise HTTPException(404, "Package not found")
    for pkg in packages:
        packaging_department_scope(current, pkg.packaging_department_code)
        if pkg.status != "returned_to_packaging":
            raise HTTPException(409, "Select returned packages only")
        _ensure_package_can_change(db, pkg)
        old = db.query(PackagePrintRunMember).join(PackagePrintRun).filter(
            PackagePrintRunMember.package_id == pkg.id, PackagePrintRun.returned_at.is_not(None),
        ).order_by(PackagePrintRun.id.desc()).first()
        if not old or old.snapshot["barcode"] == pkg.barcode:
            raise HTTPException(409, "Save the package correction before sending and printing again")
        pkg.status = "packed"
    db.flush()
    run = create_run(db, current, packages)
    log_action(db, current, "resend_corrected_packages", "PackagePrintRun", run.id, new_value={"package_ids": ids})
    return run_payload(db, run)
