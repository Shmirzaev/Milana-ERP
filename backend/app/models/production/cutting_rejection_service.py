"""Reject an unrecorded Cutting job without deleting plans or execution facts."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.libs.dto.production.work_order_rejection_input import CuttingWorkOrderRejectIn
from app.libs.enums.production import WorkOrderStatus
from app.models.audit_service import log_action
from app.models.factory_scope_service import require_factory_access, require_work_order_factory_access
from app.models.notifications_service import notify
from app.schemas import (
    Bundle, CuttingPassport, CuttingRecord, FinishedGoodsStock, ManualAccessoryIssue,
    MaterialReservation, Package, PackageBatchAllocation, PackagingReceipt, PackagingRecord,
    PayrollQrLabel, PayrollRecord, PrintingRecord, ProductionBatch, ProductionOrder,
    QualityCheck, SewingAssignment, SewingDailyReport, SewingRecord,
    SewingReplacementRequest, User, WasteRecord, WorkOrder,
)
from app.schemas.production.work_order_rejection import reject_cutting_work_order


def _has_execution_history(db: Session, order_id: int, works: list[WorkOrder]) -> bool:
    for work in works:
        if any((work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty, work.rework_qty)):
            return True
        if work.operation != "cutting" and (work.start_time or work.end_time or work.status not in {
            WorkOrderStatus.NEW, WorkOrderStatus.PLANNING, WorkOrderStatus.WAITING,
            WorkOrderStatus.PENDING, WorkOrderStatus.READY,
        }):
            return True
    work_ids = [work.id for work in works]
    batch_ids = select(ProductionBatch.id).where(ProductionBatch.production_order_id == order_id)
    for model in (CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord, QualityCheck,
                  WasteRecord, PayrollRecord, PayrollQrLabel, SewingDailyReport):
        if db.query(model.id).filter(model.work_order_id.in_(work_ids)).first():
            return True
    for model in (Package, PackageBatchAllocation, PayrollRecord, PayrollQrLabel, SewingDailyReport):
        if db.query(model.id).filter(model.production_batch_id.in_(batch_ids)).first():
            return True
    assignments = select(SewingAssignment.id).where(or_(
        SewingAssignment.work_order_id.in_(work_ids), SewingAssignment.production_batch_id.in_(batch_ids),
    ))
    if db.query(SewingDailyReport.id).filter(SewingDailyReport.sewing_assignment_id.in_(assignments)).first():
        return True
    if db.query(SewingAssignment.id).filter(or_(
        SewingAssignment.work_order_id.in_(work_ids), SewingAssignment.production_batch_id.in_(batch_ids),
    ), or_(SewingAssignment.completed_qty > 0, SewingAssignment.actual_start.isnot(None),
           SewingAssignment.actual_end.isnot(None), SewingAssignment.line_finished_at.isnot(None),
           ~SewingAssignment.status.in_(["planned", "cancelled", "transferred"]))).first():
        return True
    for model in (CuttingPassport, Bundle, Package, FinishedGoodsStock, PackagingReceipt, PayrollQrLabel,
                  PayrollRecord, SewingDailyReport, SewingReplacementRequest, WasteRecord, ManualAccessoryIssue):
        if db.query(model.id).filter(model.production_order_id == order_id).first():
            return True
    return bool(db.query(ProductionBatch.id).filter(
        ProductionBatch.production_order_id == order_id,
        or_(ProductionBatch.cutting_passport_id.isnot(None), ProductionBatch.passport_actual_quantity.isnot(None)),
    ).first() or db.query(MaterialReservation.id).filter(
        MaterialReservation.production_order_id == order_id, MaterialReservation.consumed_quantity > 0,
    ).first())


def reject_cutting_order(
    db: Session, work_order_id: int, payload: CuttingWorkOrderRejectIn, current: User,
) -> WorkOrder:
    """Own one transaction; lock order -> all stage rows, like routing/Cutting."""
    try:
        if not set(user_permissions(current)).intersection({"*", "cutting.records", "planning.production"}):
            raise HTTPException(403, "Cutting or planning permission is required")
        order_id = db.query(WorkOrder.production_order_id).filter_by(id=work_order_id).scalar()
        if order_id is None:
            raise HTTPException(404, "Work order not found")
        order = db.query(ProductionOrder).filter_by(id=order_id).with_for_update(
            of=ProductionOrder, nowait=True).populate_existing().one()
        works = db.query(WorkOrder).filter_by(production_order_id=order_id).order_by(WorkOrder.id).with_for_update(
            of=WorkOrder, nowait=True).populate_existing().all()
        work = next(row for row in works if row.id == work_order_id)
        require_work_order_factory_access(current, db, work)
        if order.source_type == "usluga":
            require_factory_access(current, "ECO")
        if work.operation != "cutting":
            raise HTTPException(400, "Only cutting work orders can be rejected here")
        if work.status == WorkOrderStatus.REJECTED:
            if work.is_blocked and work.block_reason == payload.reason:
                db.commit()
                return work
            raise HTTPException(409, "This cutting order has already been rejected")
        if work.status in {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED} or work.end_time or order.status not in {"new", "planning", "cutting"}:
            raise HTTPException(409, "This cutting order is closed and cannot be rejected")
        if _has_execution_history(db, order.id, works):
            raise HTTPException(409, "Cutting with recorded production or handoff history cannot be rejected")
        before = {"status": work.status, "is_blocked": work.is_blocked, "block_reason": work.block_reason}
        reject_cutting_work_order(work, reason=payload.reason, ended_at=datetime.now(timezone.utc))
        log_action(db, current, "reject_cutting", "WorkOrder", work.id, old_value=before,
                   new_value={"status": work.status, "reason": payload.reason, "production_order_id": order.id})
        if order.created_by and order.created_by != current.id:
            notify(db, user_id=order.created_by, title=f"Cutting rejected: {order.order_no}",
                   message=payload.reason, link=f"/production-orders/{order.id}")
        db.commit()
        db.refresh(work)
        return work
    except Exception as error:
        db.rollback()
        if isinstance(error, OperationalError) and (
            getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03"
        ):
            raise HTTPException(409, "Cutting is being updated. Reload and try again.") from error
        raise
