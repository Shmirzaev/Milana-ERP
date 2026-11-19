"""One Packaging output operation shared by legacy entry and direct labels.

The caller owns source locks, authorization, quantities and the outer transaction.
Existing workflow, BOM, waste, notification and audit operations use that Session.
"""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.libs.dto.production.production import PackagingRecordIn
from app.libs.enums.production import WorkOrderStatus
from app.models.audit_service import log_action
from app.models.workflow_service import (
    advance_workflow, consume_packaging_materials_from_bom, create_waste_record,
    notify_department,
)
from app.schemas import PackagingReceipt, PackagingRecord, ProductionOrder, User, WorkOrder
from app.schemas.packaging.output_persistence import insert_output


def record_output(db: Session, current: User, work: WorkOrder,
                  payload: PackagingRecordIn, *, reconstruct_counters: bool = False) -> PackagingRecord:
    # Old acceptance receipts may have populated WO counters: reconstruct input
    # from physical output evidence rather than adding the receipt a second time.
    output = int(work.actual_output_qty or 0) + payload.packed_qty
    passed = int(work.passed_qty or 0) + payload.packed_qty
    failed = int(work.failed_qty or 0) + payload.damaged_qty
    if reconstruct_counters or db.query(PackagingReceipt.id).filter_by(work_order_id=work.id).first():
        inputs, packed, damaged = db.query(func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
            func.coalesce(func.sum(PackagingRecord.damaged_qty), 0)).filter_by(work_order_id=work.id).one()
        previous = int(inputs or 0)
        if reconstruct_counters:
            output = passed = int(packed or 0) + payload.packed_qty
            failed = int(damaged or 0) + payload.damaged_qty
    else:
        previous = int(work.actual_input_qty or 0)
    # A direct output action starts Packaging itself; the removed record form
    # must not leave partial physical work in the READY queue. Legacy callers
    # retain their existing status policy. Completed/paused work is not reset.
    direct_start = reconstruct_counters and work.status in {
        WorkOrderStatus.NEW, WorkOrderStatus.PLANNING, WorkOrderStatus.WAITING,
        WorkOrderStatus.PENDING, WorkOrderStatus.READY, WorkOrderStatus.COLLECTED,
        WorkOrderStatus.IN_PROGRESS,
    }
    row = insert_output(db, work, payload, operator_id=payload.operator_id or current.id,
                        actual_input_qty=previous + payload.input_qty, actual_output_qty=output,
                        passed_qty=passed, failed_qty=failed,
                        started_at=datetime.now(timezone.utc) if direct_start else None)
    consume_packaging_materials_from_bom(
        db, production_order_id=work.production_order_id, packed_qty=payload.packed_qty,
        reference_type="PackagingRecord", reference_id=row.id, user_id=current.id,
    )
    create_waste_record(
        db, production_order_id=work.production_order_id, work_order_id=work.id,
        source_department_id=work.department_id, item_id=None, batch_id=None,
        waste_type="packaging_damage", quantity=float(payload.damaged_qty), unit="pcs",
        reason="Auto-created from packaging record", created_by=current.id,
    )
    advance_workflow(db, work, trigger_output_qty=payload.packed_qty)
    order = db.get(ProductionOrder, work.production_order_id)
    if payload.packed_qty > 0 and getattr(order, "source_type", "standard") != "usluga":
        notify_department(db, department_code="FGS", title="Packed goods ready",
            message=f"Order {work.order_no or work.id} packed {payload.packed_qty} pcs and is ready for storage intake.",
            link="/packages/scan")
    log_action(db, current, "create", "PackagingRecord", row.id, new_value={"work_order_id": work.id})
    return row
