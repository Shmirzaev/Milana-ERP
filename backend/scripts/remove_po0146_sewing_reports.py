"""Remove only the three reviewed PO-0146 reports and return its unused assignment.

Read-only by default. --apply requires a separately verified production backup.
All changes commit together; snapshots are retained in the system audit ledger.
"""

import argparse
import json

from sqlalchemy import or_, text

from app.db.session import SessionLocal
from app.models import (
    ProductionBatch, ProductionOrder, SewingAssignment, SewingDailyReport,
    SewingFlow, SewingRecord, WorkOrder,
)
from app.services.audit import _json_safe, log_action


REASON = "User requested deletion of PO-0146 daily reports and return from its sewing line on 2026-09-17"
REPORTS = {894: (200, 2, 1), 895: (500, 3, 1), 896: (500, 11, 2)}


def snapshot(row):
    return _json_safe({column.name: getattr(row, column.name) for column in row.__table__.columns})


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def correct(db, *, apply=False):
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
    order = db.query(ProductionOrder).filter_by(id=168).with_for_update().one()
    require((order.production_no, order.model_id, order.planned_quantity) == ("PO-0146", 8046, 600), "Order identity changed")
    work = db.query(WorkOrder).filter_by(id=651).with_for_update().one()
    assignment = db.query(SewingAssignment).filter_by(id=34).with_for_update().one()
    flow = db.get(SewingFlow, 96)
    batch = db.get(ProductionBatch, 76)
    require(flow and (flow.factory_code, flow.code) == ("BST", "BST-BAND-01"), "Line identity changed")
    require(batch and (batch.production_order_id, batch.batch_no) == (168, "0168-01"), "Batch identity changed")
    require((work.production_order_id, work.operation) == (168, "sewing"), "Work identity changed")
    require((assignment.work_order_id, assignment.sewing_flow_id, assignment.production_batch_id, assignment.quantity) == (651, 96, 76, 600), "Assignment identity changed")
    reports = db.query(SewingDailyReport).filter(or_(
        SewingDailyReport.production_order_id == 168,
        SewingDailyReport.work_order_id == 651,
        SewingDailyReport.sewing_assignment_id == 34,
        SewingDailyReport.id.in_(REPORTS),
    )).order_by(SewingDailyReport.id).with_for_update().all()
    if assignment.status == "cancelled" and not reports:
        return {"status": "already_applied", "order": "PO-0146"}
    require(assignment.status == "planned" and work.status in ("waiting", "ready", "in_progress"), "Work status changed")
    require(not assignment.completed_qty and not assignment.actual_start and not assignment.actual_end, "Assignment has production output")
    require(not any((work.actual_output_qty, work.passed_qty, work.failed_qty, work.rework_qty)), "Work order has production output")
    require(not db.query(SewingRecord.id).filter_by(work_order_id=651).first(), "Actual sewing records exist")
    require(not db.query(SewingAssignment.id).filter(
        SewingAssignment.work_order_id == 651, SewingAssignment.id != 34,
        SewingAssignment.status.in_(("planned", "in_progress", "completed")),
    ).first(), "Additional assignments exist")
    require(work.sewing_flow_id == 96, "Primary line changed")
    require([r.id for r in reports] == list(REPORTS), "Report set changed")
    for report in reports:
        require((report.sewn_qty, report.defective_qty, report.section_no) == REPORTS[report.id], "Report quantities changed")
        require((report.production_order_id, report.work_order_id, report.sewing_assignment_id, report.production_batch_id, report.sewing_flow_id) == (168, 651, 34, 76, 96), "Report linkage changed")
        require(str(report.report_date) == "2026-09-12" and report.kroy_no == "9049", "Report identity changed")
    result = {"status": "ready", "order": "PO-0146", "report_ids": list(REPORTS),
              "reported_pieces": sum(r.sewn_qty for r in reports), "returned_assignment": 34, "returned_quantity": 600}
    if not apply:
        return result
    # Serialize this audit segment against other writers while retaining all history.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
    audits = []
    for report in reports:
        audits.append(log_action(db, None, "delete", "SewingDailyReport", report.id,
                                 old_value=snapshot(report), new_value={"reason": REASON}).id)
        db.delete(report)
    old = {"assignment": snapshot(assignment), "work_order": snapshot(work)}
    assignment.status = "cancelled"
    work.sewing_flow_id = None
    db.flush()
    audits.append(log_action(db, None, "return", "SewingAssignment", assignment.id, old_value=old,
                             new_value={"reason": REASON, "assignment": snapshot(assignment), "work_order": snapshot(work)}).id)
    result.update(status="applied", audit_ids=audits)
    return result


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
