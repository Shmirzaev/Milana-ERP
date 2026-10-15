"""Apply scoped Packaging corrections directly, retaining printed evidence."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.models import Package, PackageChangeRequest, PackagePrintRun, PackagePrintRunMember, ProductionOrder
from app.services.audit import log_action
from app.services.barcode import generate_barcode_value
from app.services.numbering import _next, retire_label_numbers
from app.services.packaging_scope import require_package_access
from app.services.package_workflows import active_members, contents, run_members
from app.services.packages import (
    _apply_package_delete_request, _apply_package_edit_request, _ensure_package_can_change,
    normalize_package_edit_payload, package_snapshot,
)


def correct_package(db, current, pid, payload):
    # Receiving uses run -> order -> package -> stock. Recheck membership after
    # obtaining locks so a concurrent reprint/correction cannot bypass the gate.
    members = active_members(db).filter(PackagePrintRunMember.package_id == pid).all()
    active_run_ids = {member.run_id for member in members}
    history = db.query(PackagePrintRunMember).filter_by(package_id=pid).all() if payload.request_type == "delete" else members
    run_ids = sorted({member.run_id for member in history})
    runs = db.query(PackagePrintRun).filter(PackagePrintRun.id.in_(run_ids)).order_by(
        PackagePrintRun.id).with_for_update().populate_existing().all()
    order_id = db.query(Package.production_order_id).filter_by(id=pid).scalar()
    if order_id:
        db.query(ProductionOrder).filter_by(id=order_id).with_for_update().populate_existing().one()
    pkg = db.query(Package).filter_by(id=pid).with_for_update().populate_existing().first()
    if not pkg:
        raise HTTPException(404, "Package not found")
    require_package_access(current, pkg)
    if {m.run_id for m in active_members(db).filter(PackagePrintRunMember.package_id == pid).all()} != active_run_ids:
        raise HTTPException(409, "Package print run changed; refresh and retry")
    _ensure_package_can_change(db, pkg, allow_printed=True)
    if payload.request_type not in {"edit", "delete"}:
        raise HTTPException(400, "request_type must be edit or delete")
    target = normalize_package_edit_payload(db, pkg, payload.payload.model_dump(exclude_unset=True)
                                            if payload.payload else None) if payload.request_type == "edit" else None
    # Keep old requests as history; a newly submitted direct action replaces them.
    for pending in db.query(PackageChangeRequest).filter_by(package_id=pid, status="pending").with_for_update().all():
        pending.status = "rejected"
        pending.reviewed_by = current.id
        pending.reviewed_at = datetime.now(timezone.utc)
        pending.decision_notes = "Replaced by a direct Packaging correction"
    request = PackageChangeRequest(package_id=pid, package_no=pkg.package_no,
                                   request_type=payload.request_type, status="pending",
                                   before_json=package_snapshot(pkg), payload_json=target,
                                   reason=payload.reason, requested_by=current.id)
    db.add(request)
    db.flush()
    now = datetime.now(timezone.utc)
    if payload.request_type == "delete":
        retire_label_numbers(db, [pkg.package_no])
        for run in runs:
            if run.deleted_at is not None:
                continue
            run.deleted_package_ids = sorted(set(run.deleted_package_ids or []) | {pid})
            if set(run.deleted_package_ids) == set(run.package_ids):
                run.deleted_at = now
        _apply_package_delete_request(db, request, allow_printed=True)
    else:
        pkg = _apply_package_edit_request(db, request, current.id, allow_printed=True)
        db.expire(pkg, ["items", "batch_allocations"])
        # Old QR labels must not silently identify altered contents.
        pkg.barcode = generate_barcode_value("PKG")
        pkg.qr_code_url = None
        db.flush()
        for run in runs:
            old_members = [member for member in run_members(db, run)
                           if member.package_id not in set(run.deleted_package_ids or [])]
            run.superseded_at = now
            replacement = PackagePrintRun(
                run_no=_next(db, PackagePrintRun, "run_no", "PRN"), code=f"PACKRUN:{uuid4().hex}",
                packaging_department_code=run.packaging_department_code,
                package_ids=[member.package_id for member in old_members], created_by=current.id,
                received_by=run.received_by, received_at=run.received_at,
                receipt_location=run.receipt_location, deleted_package_ids=[],
            )
            db.add(replacement)
            db.flush()
            for member in old_members:
                db.add(PackagePrintRunMember(run_id=replacement.id, package_id=member.package_id,
                                            snapshot=contents(pkg) if member.package_id == pid else member.snapshot))
            log_action(db, current, "correct_package_print_run", "PackagePrintRun", replacement.id,
                       new_value={"previous_run_id": run.id, "package_id": pid, "reason": payload.reason})
    request.status = "approved"
    request.reviewed_by = current.id
    request.reviewed_at = now
    request.decision_notes = "Applied directly by an authorized Packaging operator"
    log_action(db, current, f"direct_package_{payload.request_type}", "PackageChangeRequest", request.id,
               old_value=request.before_json, new_value=target or {"deleted_package": request.package_no})
    db.flush()
    return request
