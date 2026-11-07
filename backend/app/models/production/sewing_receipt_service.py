"""Manual and batch-QR sewing receipts share one atomic line acceptance operation.

The existing batch lock order and receipt helpers are retained. The service owns
commit; schema helpers persist new assignment changes in its supplied Session.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NotRequired, TypedDict

from fastapi import HTTPException
from sqlalchemy import and_, or_, text, true
from sqlalchemy.orm import Session

from app.libs.dto.production.sewing_manual_receive import SewingManualReceiveIn
from app.schemas import Bundle, Department, ProductionBatch, SewingAssignment, SewingFlow, User, WorkOrder
from app.schemas.production.sewing_receipt import create_receipt_assignment, resize_receipt_assignment, start_receipt_assignment
from app.models.audit_service import log_action
from app.models.bundles_service import receive_many_at_sewing, resolve_sewing_factory_code, verify_sewing_accessory_gate
from app.models.sewing_scope_service import require_sewing_flow_access, sewing_line_factory_scope
from app.models.sewing_input_service import sewing_receipt_printing_totals, usable_sewing_receipt_quantity

SEWING_RECEIVE_DEPARTMENT_CODES = ("SEW", "MIL", "BST", "ECO")


class SewingManualReceiveResult(TypedDict):
    received_count: int
    received_quantity: int
    bundle_ids: list[int]
    sewing_flow_id: NotRequired[int]
    sewing_assignment_id: NotRequired[int]


@dataclass
class SewingBatchAcceptance:
    batch: ProductionBatch
    bundles: list[Bundle]
    flow: SewingFlow
    assignment: SewingAssignment
    received_ids: list[int]


def _sewing_receive_department_ids(db: Session) -> list[int]:
    return [
        int(id_)
        for (id_,) in db.query(Department.id)
        .filter(Department.code.in_(SEWING_RECEIVE_DEPARTMENT_CODES))
        .all()
    ]


def _sewing_receive_eligible_filter(db: Session):
    department_ids = _sewing_receive_department_ids(db)
    direct_to_sewing = Bundle.status == "sent_to_sewing"
    if not department_ids:
        return direct_to_sewing
    return or_(
        direct_to_sewing,
        and_(Bundle.status == "created", Bundle.next_department_id.in_(department_ids)),
    )


def _sewing_work_order_for_batch(db: Session, batch: ProductionBatch) -> WorkOrder | None:
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == batch.production_order_id,
        WorkOrder.operation == "sewing",
    )
    scoped = qry.filter(WorkOrder.production_batch_id == batch.id).order_by(WorkOrder.id.asc()).first()
    if scoped:
        return scoped
    return (
        qry.filter(WorkOrder.production_batch_id.is_(None)).order_by(WorkOrder.id.asc()).first()
        or qry.order_by(WorkOrder.id.asc()).first()
    )


def receive_manual_sewing(db: Session, payload: SewingManualReceiveIn, current: User) -> SewingManualReceiveResult:
    factory = sewing_line_factory_scope(current, payload.factory_code)
    if payload.sewing_flow_id is not None:
        if payload.production_batch_id is None:
            raise HTTPException(400, "Choose a Nastil to receive and assign a sewing line")
        accepted = accept_sewing_batch(
            db, payload.production_batch_id, payload.sewing_flow_id, current, manual_scope=payload,
        )
        received = set(accepted.received_ids)
        return {"received_count": len(received),
                "received_quantity": sum(int(bundle.quantity or 0) for bundle in accepted.bundles if bundle.id in received),
                "bundle_ids": accepted.received_ids, "sewing_flow_id": accepted.flow.id,
                "sewing_assignment_id": accepted.assignment.id}

    # Serialize manual receipts of sibling batches without reversing the existing
    # bundle -> work-order lock order used by individual scanner receipts.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(74201, :order_id)"), {"order_id": payload.production_order_id})
    qry = db.query(Bundle).filter(
        _sewing_receive_eligible_filter(db),
        Bundle.production_order_id == payload.production_order_id,
        Bundle.production_batch_id == payload.production_batch_id,
        Bundle.sewing_factory_code == factory,
    )
    if payload.model_id is not None:
        qry = qry.filter(Bundle.model_id == payload.model_id)
    bundles = qry.order_by(Bundle.id.asc()).with_for_update().all()
    if not bundles:
        raise HTTPException(404, "No bundles are waiting for sewing receive")

    accessory_gate = verify_sewing_accessory_gate(db, payload.production_order_id, sewing_factory_code=factory)
    received_ids = receive_many_at_sewing(
        db,
        bundles,
        current,
        accessory_gate,
        after_receive=lambda bundle: log_action(
            db, current, "manual_receive_at_sewing", "Bundle", bundle.id
        ),
    )
    received_quantity = sum(int(bundle.quantity or 0) for bundle in bundles)
    db.commit()

    return {
        "received_count": len(received_ids),
        "received_quantity": received_quantity,
        "bundle_ids": received_ids,
    }

def accept_sewing_batch(
    db: Session, production_batch_id: int, sewing_flow_id: int, current: User,
    *, manual_scope: SewingManualReceiveIn | None = None,
) -> SewingBatchAcceptance:
    batch = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.id == production_batch_id)
        .with_for_update()
        .first()
    )
    if not batch:
        raise HTTPException(404, "Production batch not found")

    if manual_scope is not None and batch.production_order_id != manual_scope.production_order_id:
        raise HTTPException(404, "Production batch not found for this production order")

    flow = db.get(SewingFlow, sewing_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing line not found")
    require_sewing_flow_access(current, flow)
    if not flow.is_active:
        raise HTTPException(400, "Sewing line is inactive")

    printing = sewing_receipt_printing_totals(batch.production_order_id, batch.id)
    bundle_rows = (
        db.query(Bundle, printing.c.printing_passed_qty, printing.c.printing_rejected_qty)
        .join(printing, true())
        .filter(
            Bundle.production_batch_id == batch.id,
            Bundle.production_order_id == batch.production_order_id,
            Bundle.status != "cancelled",
        )
        .order_by(Bundle.id.asc())
        .with_for_update(of=Bundle)
        .all()
    )
    bundles = [row[0] for row in bundle_rows]
    if not bundles:
        raise HTTPException(404, "No bundles found for this production batch")

    factory_codes = {resolve_sewing_factory_code(bundle.sewing_factory_code) for bundle in bundles}
    if len(factory_codes) != 1 or factory_codes != {flow.factory_code}:
        raise HTTPException(409, "The selected sewing line belongs to a different sewing factory")

    if manual_scope is not None:
        factory = sewing_line_factory_scope(current, manual_scope.factory_code)
        if factory_codes != {factory}:
            raise HTTPException(409, "The selected batch belongs to a different sewing factory")
        # Validate after the canonical batch/bundle locks: a model-filtered manual
        # selection must not silently widen to another historical batch model.
        if manual_scope.model_id is not None and any(bundle.model_id != manual_scope.model_id for bundle in bundles):
            raise HTTPException(409, "This Nastil contains several models; use batch acceptance to assign the complete Nastil")

    sewing_department_ids = set(_sewing_receive_department_ids(db))
    blocked = [
        bundle
        for bundle in bundles
        if bundle.status != "received_sewing"
        and bundle.status != "sent_to_sewing"
        and not (bundle.status == "created" and bundle.next_department_id in sewing_department_ids)
    ]
    if blocked:
        statuses = ", ".join(sorted({str(bundle.status) for bundle in blocked}))
        raise HTTPException(
            409,
            f"This batch is not fully ready for sewing acceptance. Blocking bundle status: {statuses}",
        )

    wo = _sewing_work_order_for_batch(db, batch)
    if not wo:
        raise HTTPException(404, "Sewing work order not found for this production batch")

    managed_statuses = ("planned", "in_progress", "completed")
    all_assignments = (
        db.query(SewingAssignment)
        .filter(
            SewingAssignment.work_order_id == wo.id,
            SewingAssignment.status.in_(managed_statuses),
        )
        .with_for_update()
        .all()
    )
    unscoped = [assignment for assignment in all_assignments if assignment.production_batch_id is None]
    if unscoped:
        raise HTTPException(409, "This sewing work order already has an order-level line assignment")

    batch_assignments = [
        assignment
        for assignment in all_assignments
        if int(assignment.production_batch_id or 0) == int(batch.id)
    ]
    has_unreceived_bundles = any(bundle.status != "received_sewing" for bundle in bundles)
    if has_unreceived_bundles and any(assignment.status == "completed" for assignment in batch_assignments):
        raise HTTPException(409, "This batch has a completed sewing assignment and cannot be accepted again")
    assigned_flow_ids = {int(assignment.sewing_flow_id) for assignment in batch_assignments}
    if assigned_flow_ids and assigned_flow_ids != {int(flow.id)}:
        assigned_names = [
            row.name or row.code
            for row in db.query(SewingFlow).filter(SewingFlow.id.in_(assigned_flow_ids)).all()
        ]
        raise HTTPException(409, f"This batch is already assigned to: {', '.join(assigned_names)}")

    if not all_assignments and wo.sewing_flow_id and int(wo.sewing_flow_id) != int(flow.id):
        current_flow = db.get(SewingFlow, wo.sewing_flow_id)
        raise HTTPException(
            409,
            f"This sewing work order is already assigned to {current_flow.name if current_flow else wo.sewing_flow_id}",
        )

    accessory_gate = (
        verify_sewing_accessory_gate(db, int(batch.production_order_id), sewing_factory_code=flow.factory_code)
        if has_unreceived_bundles
        else None
    )
    total_quantity = sum(int(bundle.quantity or 0) for bundle in bundles)
    assignment_quantity = usable_sewing_receipt_quantity(
        received_qty=total_quantity, printing_passed_qty=int(bundle_rows[0][1]),
        printing_rejected_qty=int(bundle_rows[0][2]),
    )
    if assignment_quantity <= 0:
        raise HTTPException(409, "This Nastil has no usable Sewing input after Printing rejects")
    assignment: SewingAssignment
    if batch_assignments:
        assigned_quantity = sum(int(row.quantity or 0) for row in batch_assignments)
        if assigned_quantity != assignment_quantity:
            can_resize = (
                len(batch_assignments) == 1
                and int(batch_assignments[0].completed_qty or 0) == 0
                and assigned_quantity <= assignment_quantity
            )
            if not can_resize:
                raise HTTPException(
                    409,
                    f"Existing batch assignment quantity ({assigned_quantity}) does not match usable Sewing quantity ({assignment_quantity})",
                )
            resize_receipt_assignment(batch_assignments[0], assignment_quantity)
        assignment = batch_assignments[0]
    else:
        now = datetime.now(timezone.utc)
        assignment = create_receipt_assignment(
            db, work_order=wo, production_batch_id=batch.id, sewing_flow_id=flow.id,
            quantity=assignment_quantity, now=now, planned_end=batch.deadline, actor_id=current.id,
            notes="Accepted from manual sewing receipt" if manual_scope else "Accepted from cutting-sheet batch QR",
        )

    start_receipt_assignment(assignment, wo, flow.id, datetime.now(timezone.utc))

    received_ids = (
        receive_many_at_sewing(
            db,
            [bundle for bundle in bundles if bundle.status != "received_sewing"],
            current,
            accessory_gate,
            after_receive=(lambda bundle: log_action(db, current, "manual_receive_at_sewing", "Bundle", bundle.id)) if manual_scope else None,
        )
        if accessory_gate
        else []
    )

    if wo.status == "completed":
        from app.models.sewing_progress_service import reconcile_sewing_order
        reconcile_sewing_order(db, batch.production_order_id, current=current, reason="Sewing batch accepted and assigned")

    log_action(
        db,
        current,
        "accept_sewing_batch_manual" if manual_scope else "accept_sewing_batch_qr",
        "ProductionBatch",
        batch.id,
        new_value={
            "sewing_flow_id": int(flow.id),
            "sewing_assignment_id": int(assignment.id),
            "bundle_ids": [int(bundle.id) for bundle in bundles],
            "received_bundle_ids": received_ids,
            "quantity": total_quantity,
            "assignment_quantity": assignment_quantity,
        },
    )
    db.commit()

    return SewingBatchAcceptance(batch, bundles, flow, assignment, received_ids)
