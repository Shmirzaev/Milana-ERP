"""Create physical packs in Packaging; warehouse acceptance stays separate."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.libs.dto.packaging.manual_package_input import ManualPackageCreateIn
from app.libs.enums.packaging import ManualPackageSource, ManualRecoveryStatus, PackagingDepartment
from app.libs.dto.packaging.manual_package_output import ManualPackageCreateOut, ManualPackageRecoveryOut
from app.models.audit_service import log_action
from app.models.barcode_service import generate_barcode_value, save_qr_image
from app.models.idempotency_service import (
    replay_idempotent_response, request_fingerprint, store_idempotent_response,
)
from app.models.numbering_service import _next, next_package_nos
from app.models.package_workflows_service import (
    cancelled_request_response, contents, is_cancelled_request, lock_request,
    require_active_run, run_payload,
)
from app.models.packaging_scope_service import packaging_department_scope
from app.schemas import ManualPackageReceipt, Model, PackagePrintRun, User
from app.schemas.packaging.manual_packages_persistence import (
    insert_manual_evidence, insert_manual_package, insert_manual_print_run,
    set_manual_package_qr,
)


def _replayed_run(db: Session, current: User, replay: dict) -> ManualPackageCreateOut:
    if is_cancelled_request(replay):
        raise HTTPException(409, "This package request was cancelled; submit corrected values with a new key")
    run = db.get(PackagePrintRun, replay["print_run"]["id"])
    if not run:
        raise HTTPException(410, "This package request result is no longer available")
    packaging_department_scope(current, run.packaging_department_code)
    require_active_run(run)
    if run.deleted_package_ids:
        raise HTTPException(410, "Some labels in this manual packaging request were deleted")
    return ManualPackageCreateOut.model_validate(replay)


def create_manual_packages(db: Session, current: User, payload: ManualPackageCreateIn) -> ManualPackageCreateOut:
    if not set(user_permissions(current)).intersection({"packaging.packages", "*"}):
        raise HTTPException(403, "Packaging permission required")
    department = PackagingDepartment(packaging_department_scope(current, payload.packaging_department_code.value))
    body = payload.model_dump(mode="json")
    key = str(payload.request_key)
    scope = f"packages.manual-packaging.{current.id}"
    lock_request(db, current.id, "manual-packaging", key)
    replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
    if replay is not None:
        return _replayed_run(db, current, replay)
    model = db.get(Model, payload.model_id)
    if (not model or model.catalog_scope != "standard" or model.status != "approved"
            or model.code.startswith("LEGACY-")):
        raise HTTPException(400, "Select an approved standard model/variant")
    configured = [row.size for row in model.sizes]
    if payload.pack_quantities is None:
        raise HTTPException(422, "Enter one quantity per pack")
    size = configured[0] if len(configured) == 1 else "Mixed"
    evidence = {**body, "source": ManualPackageSource.PACKAGING.value, "model_code": model.code,
                "model_name": model.name, "configured_sizes": configured,
                "total_quantity": sum(payload.pack_quantities)}
    receipt = insert_manual_evidence(
        db, receipt_no=_next(db, ManualPackageReceipt, "receipt_no", "WMR"),
        actor_id=current.id, evidence=evidence, evidence_hash=request_fingerprint(evidence),
    )
    packages = []
    try:
        for number, quantity in zip(next_package_nos(db, payload.count), payload.pack_quantities, strict=True):
            package = insert_manual_package(
                db, package_no=number, barcode=generate_barcode_value("PKG"),
                receipt_id=receipt.id, model_id=model.id, brand_id=model.brand_id,
                collection_id=model.collection_id, color=payload.color, size=size,
                quantity=quantity, weight_kg=round(payload.weight_kg, 4),
                actor_id=current.id, department=department, reason=payload.reason,
            )
            qr = save_qr_image(f"PACKAGE:{package.package_no}|{package.barcode}", f"package_qr_{package.package_no}")
            set_manual_package_qr(package, qr_url=qr)
            packages.append(package)
        run = insert_manual_print_run(
            db, run_no=_next(db, PackagePrintRun, "run_no", "PRN"), actor_id=current.id,
            department=department, packages=packages, snapshots=[contents(p) for p in packages],
        )
        log_action(db, current, "manual_packaging", "ManualPackageReceipt", receipt.id,
                   new_value={"receipt_no": receipt.receipt_no, "evidence": evidence,
                              "package_ids": [p.id for p in packages], "print_run_id": run.id})
        result = ManualPackageCreateOut(receipt_no=receipt.receipt_no, print_run=run_payload(db, run))
        store_idempotent_response(db, scope=scope, key=key, payload=body, response=result.model_dump(mode="json"), user=current)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def reconcile_manual_packages(db: Session, current: User, payload: ManualPackageCreateIn) -> ManualPackageRecoveryOut:
    key = str(payload.request_key)
    scope = f"packages.manual-packaging.{current.id}"
    body = payload.model_dump(mode="json")
    lock_request(db, current.id, "manual-packaging", key)
    replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
    if replay is not None:
        if is_cancelled_request(replay):
            return ManualPackageRecoveryOut(status=ManualRecoveryStatus.CANCELLED)
        if not set(user_permissions(current)).intersection({"packaging.packages", "*"}):
            return ManualPackageRecoveryOut(status=ManualRecoveryStatus.UNAVAILABLE)
        try:
            result = _replayed_run(db, current, replay)
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409, 410}:
                raise
            return ManualPackageRecoveryOut(status=ManualRecoveryStatus.UNAVAILABLE)
        return ManualPackageRecoveryOut(status=ManualRecoveryStatus.COMPLETED, result=result)
    store_idempotent_response(db, scope=scope, key=key, payload=body,
                             response=cancelled_request_response(), user=current, status_code=409)
    db.commit()
    return ManualPackageRecoveryOut(status=ManualRecoveryStatus.CANCELLED)


def cancel_manual_packages(db: Session, current: User, run_id: int) -> dict[str, int]:
    from app.models.package_workflows_service import delete_manual_run
    if not set(user_permissions(current)).intersection({"packaging.packages", "*"}):
        raise HTTPException(403, "Packaging permission required")
    run = db.query(PackagePrintRun).filter_by(id=run_id).with_for_update().first()
    if not run:
        raise HTTPException(404, "Print run not found")
    packaging_department_scope(current, run.packaging_department_code)
    result = delete_manual_run(db, current, run, allow_unreceived=True)
    db.commit()
    return result


def manual_package_list_context(db: Session, packages: list) -> dict[int, dict]:
    """Bounded projection for manual labels and cancellation after page reload."""
    from app.models.package_workflows_service import active_members
    from app.schemas import PackagePrintRunMember
    manual = [p for p in packages if p.manual_receipt_id]
    if not manual:
        return {}
    receipts = {row.id: row for row in db.query(ManualPackageReceipt).filter(
        ManualPackageReceipt.id.in_({p.manual_receipt_id for p in manual})).all()}
    runs = {row.package_id: row.run_id for row in active_members(db).filter(
        PackagePrintRunMember.package_id.in_([p.id for p in manual])).all()}
    return {p.id: {"print_run_id": runs.get(p.id),
                   "manual_source": {"receipt_no": receipts[p.manual_receipt_id].receipt_no,
                                     "evidence": {"source": receipts[p.manual_receipt_id].evidence.get("source")}}}
            for p in manual if p.manual_receipt_id in receipts}
