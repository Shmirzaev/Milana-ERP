"""Change an order's sewing destination before any Sewing output."""
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.schemas import (
    Bundle, Department, Package, PackagingReceipt, PackagingRecord, PayrollQrLabel,
    PayrollRecord, ProductionOrder, SewingAssignment, WorkOrder,
)
from app.models.audit_service import log_action
from app.models.cutting_batch_guard_service import require_cutting_batch_mutable
from app.models.factory_scope_service import PACKAGING_DEPARTMENTS


def change_sewing_factory(db, work, factory, current, batch_ids=None):
    try:
        if batch_ids is not None:
            from app.models.production.nastil_factory_service import change_nastil_factories
            return change_nastil_factories(db, work, factory, batch_ids, current)
        return _change(db, work, factory, current)
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03":
            raise HTTPException(409, "Sewing is being updated. Reload this batch and try again.") from error
        raise


def _change(db, work, factory, current):
    require_cutting_batch_mutable(db, work, None)
    order = db.query(ProductionOrder).filter_by(id=work.production_order_id).with_for_update(
        of=ProductionOrder, nowait=True,
    ).one()
    if order.status in {"completed", "cancelled", "rejected"} or order.source_type == "usluga":
        raise HTTPException(409, "SEWING_FACTORY_ORDER_LOCKED")
    works = db.query(WorkOrder).filter_by(production_order_id=order.id).order_by(WorkOrder.id).with_for_update(
        of=WorkOrder, nowait=True,
    ).populate_existing().all()
    require_cutting_batch_mutable(db, work, None)
    sewing = [row for row in works if row.operation == "sewing" and row.status != "cancelled"]
    packaging = [row for row in works if row.operation == "packaging" and row.status != "cancelled"]
    departments = {row.code: row for row in db.query(Department)}
    if not sewing or factory not in departments or PACKAGING_DEPARTMENTS[factory] not in departments:
        raise HTTPException(409, "SEWING_FACTORY_ORDER_LOCKED")
    target = departments[factory]
    target_packaging = departments[PACKAGING_DEPARTMENTS[factory]]
    bundles = db.query(Bundle).filter_by(production_order_id=order.id).order_by(Bundle.id).with_for_update(
        of=Bundle, nowait=True,
    ).populate_existing().all()
    live_bundles = [bundle for bundle in bundles if bundle.status != "cancelled"]
    if all(row.department_id == target.id for row in sewing) and all(
        row.sewing_factory_code == factory for row in live_bundles
    ):
        return {"sewing_factory_code": factory, "changed": False}
    # Old factory payroll/packaging evidence must never follow a routing edit.
    for model in (Package, PayrollQrLabel, PayrollRecord, PackagingReceipt):
        if db.query(model.id).filter(model.production_order_id == order.id).first():
            raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    if db.query(PackagingRecord.id).filter(PackagingRecord.work_order_id.in_([row.id for row in works])).first():
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    if any(row.actual_output_qty or row.passed_qty or row.failed_qty for row in packaging):
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    assignments = db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id.in_([row.id for row in sewing]),
    ).order_by(SewingAssignment.id).with_for_update(of=SewingAssignment, nowait=True).populate_existing().all()
    if any(row.completed_qty or row.actual_end or row.status == "completed" for row in assignments):
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    if any(row.status not in {"created", "sent_to_printing", "received_printing", "sent_to_sewing", "received_sewing"} for row in live_bundles):
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")

    def snapshot():
        return {
            "work_orders": [{"id": row.id, "department_id": row.department_id, "sewing_flow_id": row.sewing_flow_id} for row in sewing + packaging],
            "bundles": [{"id": row.id, "factory": row.sewing_factory_code,
                         "current_department_id": row.current_department_id,
                         "next_department_id": row.next_department_id} for row in live_bundles],
            "assignments": [{"id": row.id, "status": row.status} for row in assignments],
        }

    before = snapshot()
    # Receipts stay recorded with their unchanged quantities; the destination
    # department follows the corrected routing. Scan logs retain the old history.
    sewing_dept_ids = {departments[code].id for code in ("MIL", "BST", "ECO", "SEW") if code in departments}
    packaging_dept_ids = {departments[code].id for code in ("PKG", "BPK", "ECP") if code in departments}
    for bundle in live_bundles:
        bundle.sewing_factory_code = factory
        if bundle.current_department_id in sewing_dept_ids:
            bundle.current_department_id = target.id
        if bundle.next_department_id in sewing_dept_ids:
            bundle.next_department_id = target.id
        elif bundle.next_department_id in packaging_dept_ids:
            bundle.next_department_id = target_packaging.id
    for row in sewing:
        row.department_id = target.id
        row.sewing_flow_id = None
    for row in packaging:
        row.department_id = target_packaging.id
    for assignment in assignments:
        if assignment.status not in {"cancelled", "transferred"}:
            assignment.status = "cancelled"
    db.flush()
    log_action(db, current, "change_sewing_factory", "ProductionOrder", order.id,
               old_value=before, new_value={**snapshot(), "sewing_factory_code": factory})
    return {"sewing_factory_code": factory, "changed": True}
