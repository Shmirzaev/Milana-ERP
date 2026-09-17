"""Reverse only PO-0182 Batch 1's mistaken receipt; retain Extra batch 2.

Read-only unless --apply is supplied. Back up production before applying.
Original scan/audit history is preserved with explicit reversal entries.
"""

import argparse
import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import (
    Bundle, BundleScanLog, Package, ProductionBatch, ProductionOrder,
    SewingAssignment, SewingDailyReport, SewingRecord, WorkOrder,
)
from app.services.audit import _json_safe, log_action


FIRST_IDS = list(range(2789, 2795))
EXTRA_IDS = list(range(2819, 2825))
REASON = "User requested reversal of mistakenly received PO-0182 Batch 1 only; Extra batch 2 stays received, 2026-09-17"


def snapshot(row):
    return _json_safe({c.name: getattr(row, c.name) for c in row.__table__.columns})


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def correct(db, *, apply=False):
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
    order = db.query(ProductionOrder).filter_by(id=204).with_for_update().one()
    require((order.production_no, order.model_id, order.planned_quantity) == ("PO-0182", 5459, 900), "Order identity changed")
    work = db.query(WorkOrder).filter_by(id=796).with_for_update().one()
    require((work.production_order_id, work.production_batch_id, work.operation, work.department_id) == (204, None, "sewing", 8), "Work identity changed")
    require(work.status == "in_progress" and work.sewing_flow_id is None, "Work status or line changed")
    require(not any((work.actual_output_qty, work.passed_qty, work.failed_qty, work.rework_qty)), "Sewing output exists")
    for cls, column in ((SewingRecord, SewingRecord.work_order_id), (SewingAssignment, SewingAssignment.work_order_id),
                        (SewingDailyReport, SewingDailyReport.production_order_id), (Package, Package.production_order_id)):
        require(not db.query(cls.id).filter(column == (796 if cls in (SewingRecord, SewingAssignment) else 204)).first(), "Linked activity exists")
    batches = db.query(ProductionBatch).filter_by(production_order_id=204).order_by(ProductionBatch.id).all()
    require([(b.id, b.batch_no, b.planned_quantity) for b in batches] == [(89, "0204-01", 450), (95, "0204-02", 510)], "Batch identity changed")
    bundles = db.query(Bundle).filter_by(production_order_id=204).order_by(Bundle.id).with_for_update().all()
    require([b.id for b in bundles] == FIRST_IDS + EXTRA_IDS, "Bundle set changed")
    first, extra = bundles[:6], bundles[6:]
    for group, batch_id, quantity in ((first, 89, 75), (extra, 95, 85)):
        require(all((b.production_batch_id, b.model_id, b.quantity, b.sewing_factory_code) == (batch_id, 5459, quantity, "BST") for b in group), "Bundle identity changed")
    require(all(b.status == "received_sewing" and b.current_department_id == 8 for b in extra), "Extra batch receipt changed")
    if all(b.status == "created" and b.current_department_id == 4 for b in first) and work.actual_input_qty == 510:
        require(all(db.query(BundleScanLog.id).filter_by(bundle_id=b.id, scan_type="receive_sewing_reversed").first() for b in first), "Missing reversal evidence")
        return {"status": "already_applied"}
    require(work.actual_input_qty == 960, "Received total changed")
    require(all(b.status == "received_sewing" and b.current_department_id == 8 and b.next_department_id == 8 for b in first), "Batch 1 receipt changed")
    for index, bundle in enumerate(first):
        scans = db.query(BundleScanLog).filter_by(bundle_id=bundle.id).order_by(BundleScanLog.id).all()
        require(len(scans) == 2 and scans[0].scan_type == "created" and scans[0].to_department_id == 4, "Original cutting history changed")
        require((scans[1].id, scans[1].scan_type, scans[1].from_department_id, scans[1].to_department_id) == (3242 + index, "received_sewing", 4, 8), "Receipt history changed")
    result = {"status": "ready", "order": "PO-0182", "returned_batch": "0204-01", "returned_quantity": 450,
              "retained_batch": "0204-02", "retained_quantity": 510}
    if not apply:
        return result
    protected_extra = [snapshot(b) for b in extra]
    protected_order = snapshot(order)
    old_work = snapshot(work)
    if db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
    audits = []
    for bundle in first:
        old = snapshot(bundle)
        bundle.status = "created"
        bundle.current_department_id = 4
        db.add(BundleScanLog(bundle_id=bundle.id, scan_type="receive_sewing_reversed",
                             from_department_id=8, to_department_id=4, location="PO-0182 Batch 1 receipt correction"))
        db.flush()
        audits.append(log_action(db, None, "reverse_sewing_receipt", "Bundle", bundle.id,
                                 old_value=old, new_value={"reason": REASON, "bundle": snapshot(bundle)}).id)
    work.actual_input_qty = 510
    db.flush()
    audits.append(log_action(db, None, "correct_received_quantity", "WorkOrder", work.id,
                             old_value=old_work, new_value={"reason": REASON, "work_order": snapshot(work)}).id)
    require([snapshot(b) for b in extra] == protected_extra and snapshot(order) == protected_order, "Protected rows changed")
    return {**result, "status": "applied", "audit_ids": audits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = correct(db, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
