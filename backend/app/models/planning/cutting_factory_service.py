"""Planning may correct unrecorded Cutting routing; execution facts never move.

The PATCH operation owns one transaction, locking ProductionOrder then all its
WorkOrders with NOWAIT. Existing Cutting/passport writers use the same locks.
Audit persistence participates in that Session. GET never writes or locks.
"""
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.deps import factory_codes_with_permission, user_permissions
from app.libs.dto.planning.production_cutting_factory import (
    ProductionCuttingFactoryIn, ProductionCuttingFactoryOut,
)
from app.libs.enums.production import CuttingDepartmentCode, CuttingFactoryLockReason
from app.models.audit_service import log_action
from app.models.factory_scope_service import factory_for_department
from app.schemas import (
    Bundle, CuttingPassport, CuttingRecord, Department, FinishedGoodsStock, ManualAccessoryIssue,
    MaterialReservation, Package, PackageBatchAllocation, PackagingReceipt, PackagingRecord,
    PayrollQrLabel, PayrollRecord, PrintingRecord, ProductionBatch,
    ProductionOrder, QualityCheck, SewingAssignment, SewingDailyReport,
    SewingRecord, SewingReplacementRequest, User, WasteRecord, WorkOrder,
)
from app.schemas.production.cutting_factory_persistence import set_cutting_work_order_department


def _authorize(current: User) -> set[str]:
    granted = set(user_permissions(current))
    if "*" not in granted and "planning.production" not in granted:
        raise HTTPException(403, "Planning production permission is required")
    return set(factory_codes_with_permission(current, "planning.production"))


def _load(
    db: Session, order_id: int, current: User, *, lock: bool,
) -> tuple[ProductionOrder, list[WorkOrder], list[WorkOrder], CuttingDepartmentCode, list[CuttingDepartmentCode]]:
    allowed = _authorize(current)
    query = db.query(ProductionOrder).filter_by(id=order_id)
    if lock:
        query = query.with_for_update(of=ProductionOrder, nowait=True).populate_existing()
    order = query.first()
    if order is None:
        raise HTTPException(404, "Production order not found")
    query = db.query(WorkOrder).filter_by(production_order_id=order_id).order_by(WorkOrder.id)
    if lock:
        query = query.with_for_update(of=WorkOrder, nowait=True).populate_existing()
    works = query.all()
    cutting = [work for work in works if work.operation == "cutting"]
    codes = {code for (code,) in db.query(Department.code).filter(
        Department.id.in_([work.department_id for work in cutting]),
    )}
    if any(factory_for_department(code) not in allowed for code in codes):
        raise HTTPException(403, "Production order is outside your authorized planning factories")
    if len(codes) != 1 or not cutting:
        raise HTTPException(409, CuttingFactoryLockReason.ROUTING_LOCKED.value)
    try:
        source = CuttingDepartmentCode(next(iter(codes)))
    except ValueError:
        raise HTTPException(409, CuttingFactoryLockReason.ROUTING_LOCKED.value) from None
    available = [code for code in CuttingDepartmentCode if factory_for_department(code.value) in allowed]
    return order, works, cutting, source, available


def _lock_reason(db: Session, order: ProductionOrder, works: list[WorkOrder]) -> CuttingFactoryLockReason | None:
    if order.source_type != "standard" or order.status not in {"new", "planning", "cutting"}:
        return CuttingFactoryLockReason.ORDER_LOCKED
    for work in works:
        if any((work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty, work.rework_qty)):
            return CuttingFactoryLockReason.HISTORY_LOCKED
        if work.operation == "cutting":
            # Creation automatically starts Cutting; start_time alone is not evidence.
            if work.assigned_to is not None:
                return CuttingFactoryLockReason.ASSIGNMENT_LOCKED
            if work.status not in {"new", "planning", "waiting", "pending", "ready", "in_progress"} or work.end_time or work.is_blocked:
                return CuttingFactoryLockReason.HISTORY_LOCKED
        elif work.status not in {"new", "planning", "waiting", "pending", "ready"} or work.start_time or work.end_time:
            return CuttingFactoryLockReason.HISTORY_LOCKED
    work_ids = [work.id for work in works]
    for model in (CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord, QualityCheck,
                  WasteRecord, PayrollRecord, PayrollQrLabel, SewingDailyReport):
        if db.query(model.id).filter(model.work_order_id.in_(work_ids)).first():
            return CuttingFactoryLockReason.HISTORY_LOCKED
    batch_ids = select(ProductionBatch.id).where(ProductionBatch.production_order_id == order.id)
    # These ledgers permit a batch reference without a ProductionOrder reference.
    for model in (Package, PackageBatchAllocation, PayrollRecord, PayrollQrLabel, SewingDailyReport):
        if db.query(model.id).filter(model.production_batch_id.in_(batch_ids)).first():
            return CuttingFactoryLockReason.HISTORY_LOCKED
    assignment_ids = select(SewingAssignment.id).where(
        or_(SewingAssignment.work_order_id.in_(work_ids), SewingAssignment.production_batch_id.in_(batch_ids)),
    )
    if db.query(SewingDailyReport.id).filter(SewingDailyReport.sewing_assignment_id.in_(assignment_ids)).first():
        return CuttingFactoryLockReason.HISTORY_LOCKED
    if db.query(SewingAssignment.id).filter(
        or_(SewingAssignment.work_order_id.in_(work_ids), SewingAssignment.production_batch_id.in_(batch_ids)),
        or_(SewingAssignment.completed_qty > 0, SewingAssignment.actual_start.isnot(None),
            SewingAssignment.actual_end.isnot(None), SewingAssignment.line_finished_at.isnot(None),
            ~SewingAssignment.status.in_(["planned", "cancelled", "transferred"])),
    ).first():
        return CuttingFactoryLockReason.HISTORY_LOCKED
    for model in (CuttingPassport, Bundle, Package, FinishedGoodsStock, PackagingReceipt, PayrollQrLabel,
                  PayrollRecord, SewingDailyReport, SewingReplacementRequest, WasteRecord, ManualAccessoryIssue):
        if db.query(model.id).filter(model.production_order_id == order.id).first():
            return CuttingFactoryLockReason.HISTORY_LOCKED
    if db.query(ProductionBatch.id).filter(
        ProductionBatch.production_order_id == order.id,
        or_(ProductionBatch.cutting_passport_id.isnot(None), ProductionBatch.passport_actual_quantity.isnot(None)),
    ).first() or db.query(MaterialReservation.id).filter(
        MaterialReservation.production_order_id == order.id, MaterialReservation.consumed_quantity > 0,
    ).first():
        return CuttingFactoryLockReason.HISTORY_LOCKED
    return None


def _result(
    db: Session, order: ProductionOrder, works: list[WorkOrder],
    source: CuttingDepartmentCode, available: list[CuttingDepartmentCode], *, changed: bool = False,
) -> ProductionCuttingFactoryOut:
    reason = _lock_reason(db, order, works)
    if reason is None and not any(code != source for code in available):
        reason = CuttingFactoryLockReason.DESTINATION_DENIED
    return ProductionCuttingFactoryOut(
        production_order_id=order.id, cutting_department_code=source,
        available_departments=available, can_change=reason is None,
        lock_reason=reason, changed=changed,
    )


def cutting_factory_options(db: Session, order_id: int, current: User) -> ProductionCuttingFactoryOut:
    order, works, _, source, available = _load(db, order_id, current, lock=False)
    return _result(db, order, works, source, available)


def change_cutting_factory(
    db: Session, order_id: int, payload: ProductionCuttingFactoryIn, current: User,
) -> ProductionCuttingFactoryOut:
    try:
        order, works, cutting, source, available = _load(db, order_id, current, lock=True)
        target = payload.cutting_department_code
        if target not in available:
            raise HTTPException(403, CuttingFactoryLockReason.DESTINATION_DENIED.value)
        if target == source:
            result = _result(db, order, works, source, available)
        else:
            reason = _lock_reason(db, order, works)
            if reason is not None:
                raise HTTPException(409, reason.value)
            department = db.query(Department).filter_by(code=target.value).first()
            if department is None:
                raise HTTPException(409, CuttingFactoryLockReason.ROUTING_LOCKED.value)
            set_cutting_work_order_department(db, cutting, department.id)
            log_action(
                db, current, "change_cutting_factory", "ProductionOrder", order.id,
                old_value={"cutting_department_code": source.value},
                new_value={"cutting_department_code": target.value, "work_order_ids": [work.id for work in cutting]},
            )
            result = _result(db, order, works, target, available, changed=True)
        db.commit()
        return result
    except Exception as error:
        db.rollback()
        if isinstance(error, OperationalError) and (
            getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03"
        ):
            raise HTTPException(409, "CUTTING_FACTORY_BUSY") from error
        raise
