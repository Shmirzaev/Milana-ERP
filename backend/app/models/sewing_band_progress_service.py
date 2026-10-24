"""Daily-report progress is separate from validated production output."""
from collections import Counter

from sqlalchemy import case, func, or_
from sqlalchemy.orm import joinedload

from app.models import Model, ProductionOrder, SewingAssignment, SewingDailyReport, SewingFlow, SewingRecord, WorkOrder


def band_board(db, flow_ids):
    flows = db.query(SewingFlow).filter(SewingFlow.id.in_(flow_ids)).order_by(SewingFlow.code).all()
    assignments = (
        db.query(SewingAssignment)
        .options(joinedload(SewingAssignment.work_order).joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order),
                 joinedload(SewingAssignment.production_batch))
        .join(WorkOrder, WorkOrder.id == SewingAssignment.work_order_id)
        .filter(SewingAssignment.sewing_flow_id.in_(flow_ids),
                SewingAssignment.status.in_(("planned", "in_progress", "completed")),
                WorkOrder.status != "cancelled")
        .order_by(SewingAssignment.id.desc()).all()
    )
    model_ids = {a.work_order.production_order.model_id for a in assignments}
    models = {m.id: m.code for m in db.query(Model).filter(Model.id.in_(model_ids)).all()} if model_ids else {}
    reports = db.query(
        SewingDailyReport.sewing_assignment_id, SewingDailyReport.sewing_flow_id,
        SewingDailyReport.work_order_id, SewingDailyReport.production_batch_id,
        func.sum(case((SewingDailyReport.top_qty.is_not(None), SewingDailyReport.top_qty), else_=SewingDailyReport.sewn_qty)),
        func.sum(case((SewingDailyReport.bottom_qty.is_not(None), SewingDailyReport.bottom_qty), else_=SewingDailyReport.sewn_qty)),
    ).filter(or_(SewingDailyReport.sewing_flow_id.in_(flow_ids), SewingDailyReport.sewing_assignment_id.in_([a.id for a in assignments]))).group_by(
        SewingDailyReport.sewing_assignment_id, SewingDailyReport.sewing_flow_id,
        SewingDailyReport.work_order_id, SewingDailyReport.production_batch_id,
    ).all()
    exact, legacy = {}, {}
    for aid, fid, wid, bid, top, bottom in reports:
        target, key = (exact, aid) if aid else (legacy, (fid, wid, bid))
        old = target.get(key, (0, 0))
        target[key] = (old[0] + int(top or 0), old[1] + int(bottom or 0))
    counts = Counter((a.sewing_flow_id, a.work_order_id, a.production_batch_id) for a in assignments)
    actuals = {aid: (int(passed or 0), int(failed or 0)) for aid, passed, failed in db.query(
        SewingRecord.sewing_assignment_id, func.sum(SewingRecord.passed_qty), func.sum(SewingRecord.failed_qty + SewingRecord.rejected_qty),
    ).filter(SewingRecord.sewing_assignment_id.in_([a.id for a in assignments])).group_by(SewingRecord.sewing_assignment_id).all()} if assignments else {}
    jobs = {f.id: [] for f in flows}
    for a in assignments:
        wo = a.work_order
        po = wo.production_order
        key = (a.sewing_flow_id, a.work_order_id, a.production_batch_id)
        top, bottom = exact.get(a.id, (0, 0))
        # Attribute older unlinked reports only when the mapping is unambiguous.
        if counts[key] == 1:
            lt, lb = legacy.get(key, (0, 0))
            top, bottom = top + lt, bottom + lb
        reported = min(top, bottom)
        finished = bool(a.line_finished_at or reported >= a.quantity or a.status == "completed" or wo.status == "completed")
        batch = a.production_batch
        jobs[a.sewing_flow_id].append({
            "id": a.id, "work_order_id": wo.id, "production_order_id": po.id,
            "production_batch_id": a.production_batch_id,
            "order_no": wo.order_no or po.production_no,
            "model": models.get(po.model_id),
            "batch": batch.batch_no if batch else None,
            "quantity": a.quantity, "reported_qty": reported,
            "top_qty": top, "bottom_qty": bottom,
            "actual_qty": actuals.get(a.id, (0, 0))[0], "actual_defective_qty": actuals.get(a.id, (0, 0))[1], "line_finished": finished,
            "finish_reason": a.line_finish_reason,
            "awaiting_final": finished and a.status != "completed" and wo.status != "completed",
            "status": a.status,
        })
    return [{"id": f.id, "name": f.name, "code": f.code, "jobs": jobs[f.id]} for f in flows]
