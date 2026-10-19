"""Owner-authorized, guarded reassignment of six unstarted BSO cutting orders.

The caller must verify a fresh database backup and the active release before
invoking apply. Dry-run rolls back; no other department or quantity is changed.
"""
import argparse
import json

from app.models import Bundle, CuttingPassport, CuttingRecord, Department, ProductionOrder, WorkOrder
from app.services.audit import log_action

ORDER_NUMBERS = tuple(f"PO-{number:04d}" for number in range(339, 345))


def reassign(db, *, backup: str):
    if not backup.startswith("/opt/milana-erp/shared/backups/") or not backup.endswith(".dump"):
        raise ValueError("A verified production backup path is required")
    orders = db.query(ProductionOrder).filter(ProductionOrder.production_no.in_(ORDER_NUMBERS)).order_by(
        ProductionOrder.id).with_for_update().all()
    if {row.production_no for row in orders} != set(ORDER_NUMBERS):
        raise ValueError("Expected exactly PO-0339 through PO-0344")
    departments = dict(db.query(Department.code, Department.id).filter(Department.code.in_(["CUT", "ECT"])).all())
    if set(departments) != {"CUT", "ECT"}:
        raise ValueError("Both cutting departments must exist")
    changes = []
    for po in orders:
        if po.source_type != "standard" or po.production_type != "branded_stock":
            raise ValueError(f"Unexpected order type: {po.production_no}")
        wo = db.query(WorkOrder).filter_by(production_order_id=po.id, operation="cutting").with_for_update().one()
        if wo.department_id == departments["ECT"]:
            continue
        if wo.department_id != departments["CUT"] or wo.status not in {"waiting", "planned", "in_progress"}:
            raise ValueError(f"Cutting assignment changed: {po.production_no}")
        if any((wo.actual_input_qty, wo.actual_output_qty, wo.passed_qty, wo.failed_qty)):
            raise ValueError(f"Cutting has activity: {po.production_no}")
        if (db.query(CuttingRecord.id).filter_by(work_order_id=wo.id).first()
                or db.query(Bundle.id).filter_by(production_order_id=po.id).first()
                or db.query(CuttingPassport.id).filter_by(production_order_id=po.id).first()):
            raise ValueError(f"Cutting evidence appeared: {po.production_no}")
        before = {"department_id": wo.department_id, "department_code": "CUT"}
        wo.department_id = departments["ECT"]
        audit = log_action(db, None, "correct_cutting_factory", "WorkOrder", wo.id,
                           old_value=before, new_value={"department_id": wo.department_id,
                           "department_code": "ECT", "production_no": po.production_no,
                           "reason": "Owner requested Eco Cotton Cutting for PO-0339 through PO-0344", "backup": backup})
        changes.append((po.production_no, wo.id, audit))
    return changes


def main():
    from app.db.session import SessionLocal
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        changes = reassign(db, backup=args.backup)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({"applied": args.apply, "changes": [
            {"production_no": number, "work_order_id": wid, "audit_id": audit.id}
            for number, wid, audit in changes]}))


if __name__ == "__main__":
    main()
