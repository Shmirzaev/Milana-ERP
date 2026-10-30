from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.libs.dto.production.production import SewingRecordIn
from app.libs.types.production import (
    SewingOutputAccounting, SewingOutputAssignmentTransitionStatus, SewingOutputRecordValues,
    SewingSizeQuantity,
)
from app.models.audit_service import log_action
from app.models.bundles_service import sync_packaging_department_for_bundle_route
from app.models.factory_scope_service import require_work_order_factory_access
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.inventory_service import ensure_accessories_issued_for_sewing
from app.models.sewing_input_service import sync_sewing_input
from app.models.sewing_scope_service import require_sewing_flow_access
from app.models.workflow_service import advance_workflow, create_waste_record, notify_department
from app.schemas import (
    Bundle, CuttingRecord, PrintingRecord, ProductionBatch, ProductionOrder,
    ProductionOrderItem, SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder,
)
from app.schemas.production import sewing_output_persistence


_MAX_SEWING_SIZE_QUANTITY_ROWS = 1000


class SewingOutputResult(TypedDict):
    id: int


class SewingOutputError(Exception):
    """Expected operation refusal mapped by the HTTP adapter."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _context_work_order(db: Session, source_wo: WorkOrder, operation: str,
                        batch_id: int | None = None) -> WorkOrder | None:
    query = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == source_wo.production_order_id,
        WorkOrder.operation == operation,
    )
    target_batch = batch_id if batch_id is not None else source_wo.production_batch_id
    if target_batch is not None:
        return query.filter(
            (WorkOrder.production_batch_id == target_batch) | WorkOrder.production_batch_id.is_(None)
        ).order_by(case((WorkOrder.production_batch_id == target_batch, 0), else_=1), WorkOrder.id).first()
    return query.filter(WorkOrder.production_batch_id.is_(None)).order_by(WorkOrder.id).first()


def _resolve_record_batch_id(db: Session, wo: WorkOrder, payload_batch_id: int | None) -> int | None:
    normalized = int(payload_batch_id) if payload_batch_id else None
    if wo.production_batch_id is not None:
        expected = int(wo.production_batch_id)
        if normalized is not None and normalized != expected:
            raise SewingOutputError(400, f"This work order is bound to batch #{expected}")
        return expected
    if wo.operation in {"sewing", "packaging"}:
        from app.models.production.batch_scope_service import dedicated_batch_ids, batch_owned_by_work_order
        if not db.get(ProductionOrder, wo.production_order_id):
            raise SewingOutputError(404, "Production order not found")
        rows = db.query(ProductionBatch.id, ProductionBatch.id.notin_(
            dedicated_batch_ids(wo.production_order_id, wo.operation)
        )).filter(ProductionBatch.production_order_id == wo.production_order_id).all()
        if not rows:
            if normalized is not None and not batch_owned_by_work_order(db, wo, normalized):
                raise SewingOutputError(409, "This Nastil belongs to its dedicated work order")
            return None
        owned = {batch_id for batch_id, available in rows if available}
        if not owned:
            raise SewingOutputError(409, "This work order has no assigned Nastils")
        if normalized is None:
            raise SewingOutputError(400, "Select a production batch for this sewing record")
        if normalized not in {batch_id for batch_id, _ in rows}:
            raise SewingOutputError(404, "Production batch not found for this production order")
        if normalized not in owned:
            raise SewingOutputError(409, "This Nastil belongs to its dedicated work order")
        return normalized
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise SewingOutputError(404, "Production order not found")
    batches = db.query(ProductionBatch).filter(
        ProductionBatch.production_order_id == po.id
    ).order_by(ProductionBatch.batch_index, ProductionBatch.id).all()
    if not batches:
        if normalized is not None:
            from app.models.production.batch_scope_service import batch_owned_by_work_order
            if not batch_owned_by_work_order(db, wo, normalized):
                raise SewingOutputError(409, "This Nastil belongs to its dedicated work order")
        return None
    if normalized is None:
        raise SewingOutputError(400, "Select a production batch for this sewing record")
    if not db.query(ProductionBatch.id).filter(
        ProductionBatch.id == normalized, ProductionBatch.production_order_id == po.id
    ).first():
        raise SewingOutputError(404, "Production batch not found for this production order")
    from app.models.production.batch_scope_service import batch_owned_by_work_order
    if not batch_owned_by_work_order(db, wo, normalized):
        raise SewingOutputError(409, "This Nastil belongs to its dedicated work order")
    return normalized


def _size_key(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _sewing_size_plan(db: Session, wo: WorkOrder, batch_id: int | None) -> list[tuple[str, int]]:
    query = db.query(Bundle.size, func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == wo.production_order_id, Bundle.status != "cancelled",
    )
    query = query.filter(Bundle.production_batch_id.is_(None) if batch_id is None
                         else Bundle.production_batch_id == batch_id)
    rows = [(str(size).strip(), int(qty or 0)) for size, qty in
            query.group_by(Bundle.size).order_by(Bundle.size).all()
            if str(size or "").strip() and int(qty or 0) > 0]
    if rows:
        return rows
    items = db.query(ProductionOrderItem).filter(
        ProductionOrderItem.production_order_id == wo.production_order_id
    ).order_by(ProductionOrderItem.id).all()
    totals: dict[str, tuple[str, int]] = {}
    for item in items:
        size = str(item.size or "").strip()
        key = _size_key(size)
        if key:
            display, quantity = totals.get(key, (size, 0))
            totals[key] = display, quantity + max(0, int(item.planned_quantity or 0))
    planned = list(totals.values())
    if batch_id is None:
        return planned
    batch = db.get(ProductionBatch, batch_id)
    if not batch or batch.production_order_id != wo.production_order_id:
        raise SewingOutputError(400, "Selected production batch does not belong to this work order")
    total = sum(q for _, q in planned)
    target = max(0, int(batch.planned_quantity or 0))
    if target <= 0 or total <= 0:
        return [(size, 0) for size, _ in planned]
    allocated = []
    for index, (size, quantity) in enumerate(planned):
        numerator = target * max(0, quantity)
        allocated.append([index, size, numerator // total, numerator % total])
    left = target - sum(row[2] for row in allocated)
    for row in sorted(allocated, key=lambda r: (-r[3], r[0]))[:left]:
        row[2] += 1
    return [(row[1], row[2]) for row in allocated]


def _validated_size_quantities(db: Session, wo: WorkOrder, batch_id: int | None,
                               payload: SewingRecordIn) -> list[SewingSizeQuantity]:
    if len(payload.size_quantities) > _MAX_SEWING_SIZE_QUANTITY_ROWS:
        raise SewingOutputError(422, f"size_quantities cannot exceed {_MAX_SEWING_SIZE_QUANTITY_ROWS} rows")
    if not payload.size_quantities:
        return []
    submitted: dict[str, SewingSizeQuantity] = {}
    for item in payload.size_quantities:
        size = str(item.size or "").strip()
        key = _size_key(size)
        if not key:
            raise SewingOutputError(400, "Each sewing size must have a name")
        if key in submitted:
            submitted[key]["quantity"] = int(submitted[key]["quantity"]) + int(item.quantity)
        else:
            submitted[key] = {"size": size, "quantity": int(item.quantity)}
    if sum(int(row["quantity"]) for row in submitted.values()) != int(payload.passed_qty or 0):
        raise SewingOutputError(400, "Sewing size quantities must equal the passed output quantity")
    planned = _sewing_size_plan(db, wo, batch_id)
    by_size = {_size_key(size): size for size, _ in planned}
    if by_size:
        unknown = [str(row["size"]) for key, row in submitted.items() if key not in by_size]
        if unknown:
            raise SewingOutputError(400, f"Unknown sewing size(s): {', '.join(unknown)}")
        for key, row in submitted.items():
            row["size"] = by_size[key]
    return list(submitted.values())


def _require_confirmed_cutting_output(cutting_passed: int, *quantities: int) -> None:
    if cutting_passed <= 0 and any(quantity > 0 for quantity in quantities):
        raise SewingOutputError(400, "Record Cutting output before entering Sewing input or output")


def _revised_input_limit(db: Session, wo: WorkOrder, batch_id: int, cutting_passed: int) -> int:
    if cutting_passed <= 0:
        return 0
    from app.schemas import AuditLog
    revised = db.query(ProductionBatch.planned_quantity).join(
        ProductionOrder, ProductionOrder.id == ProductionBatch.production_order_id,
    ).filter(
        ProductionBatch.id == batch_id,
        ProductionBatch.production_order_id == wo.production_order_id,
        ProductionOrder.source_type == "standard",
        db.query(AuditLog.id).filter(
            AuditLog.entity_type == "ProductionBatch", AuditLog.entity_id == batch_id,
            AuditLog.action == "update_cutting_batch",
            AuditLog.new_value_json["planned_quantity"].as_integer() == ProductionBatch.planned_quantity,
            AuditLog.old_value_json["planned_quantity"].as_integer() != AuditLog.new_value_json["planned_quantity"].as_integer(),
        ).exists(),
    ).scalar()
    return max(cutting_passed, int(revised or 0))


def _raise_output_plans(db: Session, wo: WorkOrder) -> None:
    if wo.passed_qty <= int(wo.planned_output_qty or 0):
        return
    downstream = [row for operation in ("packaging", "storage_transfer")
                  if (row := _context_work_order(db, wo, operation)) is not None]
    from app.schemas.production.sewing_output_persistence import raise_sewing_output_plans
    raise_sewing_output_plans(wo, downstream, int(wo.passed_qty))


def _band_context(db: Session, actor, assignment_id: int, payload: SewingRecordIn) -> SewingAssignment:
    flow = db.get(SewingFlow, actor.sewing_band_id) if actor.sewing_band_id else None
    if not flow or not flow.is_active:
        raise SewingOutputError(403, "A sewing band account is required")
    require_sewing_flow_access(actor, flow)
    assignment = db.get(SewingAssignment, assignment_id)
    if not assignment or assignment.sewing_flow_id != flow.id:
        raise SewingOutputError(404, "Assignment not found for this band")
    if assignment.status not in ("planned", "in_progress", "completed"):
        raise SewingOutputError(409, "Assignment was returned or cancelled")
    if (payload.input_qty != 0 or payload.rework_qty != 0 or payload.rejected_qty != 0
            or payload.operator_id not in (None, actor.id)
            or payload.sewn_qty != payload.passed_qty + payload.failed_qty or payload.sewn_qty <= 0):
        raise SewingOutputError(400, "Enter positive final accepted/defective quantities; receipt input is recorded separately")
    if payload.failed_qty and not (payload.defect_reason or "").strip():
        raise SewingOutputError(400, "A defect reason is required")
    if payload.work_order_id != assignment.work_order_id or payload.sewing_assignment_id != assignment.id:
        raise SewingOutputError(403, "Output must belong to the selected assignment")
    if payload.production_batch_id != assignment.production_batch_id:
        raise SewingOutputError(403, "Output must belong to the selected batch")
    return assignment


def _validate_band_capacity(db: Session, wo: WorkOrder, assignment: SewingAssignment,
                            payload: SewingRecordIn, flow_id: int) -> None:
    if assignment.sewing_flow_id != flow_id or assignment.status not in ("planned", "in_progress", "completed"):
        raise SewingOutputError(409, "This assignment changed; refresh before recording output")
    if payload.passed_qty + payload.failed_qty + payload.rejected_qty > max(
        0, assignment.quantity - assignment.completed_qty,
    ):
        raise SewingOutputError(400, "Output exceeds the remaining assignment quantity")
    received = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == wo.production_order_id,
        Bundle.status == "received_sewing", Bundle.sewing_factory_code == "ECO",
    )
    recorded = db.query(func.coalesce(func.sum(
        SewingRecord.passed_qty + SewingRecord.failed_qty + SewingRecord.rejected_qty,
    ), 0)).filter(SewingRecord.work_order_id == wo.id)
    if assignment.production_batch_id is not None:
        received = received.filter(Bundle.production_batch_id == assignment.production_batch_id)
        recorded = recorded.filter(SewingRecord.production_batch_id == assignment.production_batch_id)
    if int(recorded.scalar() or 0) + payload.sewn_qty > int(received.scalar() or 0):
        raise SewingOutputError(409, "Final output exceeds bundles received for this work")


def _record_sewing_output(
    db: Session, *, actor: User, payload: SewingRecordIn, idempotency_key: str | None,
    band_assignment_id: int | None = None,
) -> SewingOutputResult | dict:
    """Record factory or band Sewing output; the caller's Session commits once here."""
    band_assignment = _band_context(db, actor, band_assignment_id, payload) if band_assignment_id is not None else None
    if band_assignment is not None:
        replay = replay_idempotent_response(db, scope="sewing:output", key=idempotency_key,
                                            payload=payload.model_dump())
        if replay is not None:
            return replay
        db.query(WorkOrder).filter(WorkOrder.id == band_assignment.work_order_id).with_for_update().one()
        db.refresh(band_assignment)
        if band_assignment.sewing_flow_id != actor.sewing_band_id or band_assignment.status not in (
            "planned", "in_progress", "completed",
        ):
            raise SewingOutputError(409, "This assignment changed; refresh before recording output")
        band_wo = db.get(WorkOrder, band_assignment.work_order_id)
        _validate_band_capacity(db, band_wo, band_assignment, payload, int(actor.sewing_band_id))

    replay = replay_idempotent_response(db, scope="sewing:output", key=idempotency_key,
                                        payload=payload.model_dump())
    if replay is not None:
        return replay
    wo = db.query(WorkOrder).filter(WorkOrder.id == payload.work_order_id).with_for_update().first()
    if not wo:
        raise SewingOutputError(404, "Work order not found")
    require_work_order_factory_access(actor, db, wo)
    if wo.operation != "sewing":
        raise SewingOutputError(400, "Work order is not a sewing operation")
    ensure_accessories_issued_for_sewing(db, int(wo.production_order_id))
    if wo.is_blocked:
        raise SewingOutputError(409, f"Work order is blocked: {wo.block_reason or 'no reason given'}")

    assignment = db.get(SewingAssignment, payload.sewing_assignment_id) if payload.sewing_assignment_id else None
    if payload.sewing_assignment_id and not assignment:
        raise SewingOutputError(404, "Sewing assignment not found")
    if assignment and assignment.work_order_id != wo.id:
        raise SewingOutputError(400, "Selected sewing assignment does not belong to this work order")
    if assignment and assignment.status not in ("planned", "in_progress", "completed"):
        raise SewingOutputError(409, "Sewing assignment has been returned or cancelled")
    if not assignment and payload.line_name:
        line_key = payload.line_name.strip().lower()
        if line_key:
            from app.schemas import SewingFlow
            assignment = db.query(SewingAssignment).join(
                SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id,
            ).filter(SewingAssignment.work_order_id == wo.id,
                     SewingAssignment.status.in_(("planned", "in_progress", "completed")),
                     (func.lower(SewingFlow.code) == line_key) | (func.lower(SewingFlow.name) == line_key)
            ).order_by(SewingAssignment.id.desc()).first()

    payload_batch_id = payload.production_batch_id
    if assignment and assignment.production_batch_id is not None:
        expected_batch = int(assignment.production_batch_id)
        if payload_batch_id and int(payload_batch_id) != expected_batch:
            raise SewingOutputError(400, "Selected sewing assignment belongs to a different production batch")
        payload_batch_id = expected_batch
    batch_id = _resolve_record_batch_id(db, wo, payload_batch_id)
    sizes = _validated_size_quantities(db, wo, batch_id, payload)
    cutting_passed = 0
    cut_wo = _context_work_order(db, wo, "cutting")
    printing_wo = _context_work_order(db, wo, "printing")
    if batch_id is not None:
        printing_passed = int(db.query(func.coalesce(func.sum(PrintingRecord.passed_qty), 0)).filter(
            PrintingRecord.work_order_id == printing_wo.id,
            PrintingRecord.production_batch_id == batch_id,
        ).scalar() or 0) if printing_wo else 0
        cutting_passed = int(db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0)).filter(
            CuttingRecord.work_order_id == cut_wo.id,
            CuttingRecord.production_batch_id == batch_id,
        ).scalar() or 0) if cut_wo else 0
        upstream = printing_passed if printing_passed > 0 else cutting_passed
        if not printing_wo or printing_wo.status == "skipped":
            upstream = _revised_input_limit(db, wo, batch_id, cutting_passed)
        current_input = int(db.query(func.coalesce(func.sum(SewingRecord.input_qty), 0)).filter(
            SewingRecord.work_order_id == wo.id, SewingRecord.production_batch_id == batch_id,
        ).scalar() or 0)
    else:
        cutting_passed = int(cut_wo.passed_qty or 0) if cut_wo else 0
        upstream = int(printing_wo.passed_qty if printing_wo and printing_wo.passed_qty else
                       cut_wo.passed_qty if cut_wo else 0)
        current_input = int(db.query(func.coalesce(func.sum(SewingRecord.input_qty), 0)).filter(
            SewingRecord.work_order_id == wo.id,
        ).scalar() or 0)
    next_input = current_input + int(payload.input_qty or 0)
    if next_input > upstream:
        if batch_id is None:
            raise SewingOutputError(400, f"Sewing input {next_input} exceeds upstream passed {upstream}")
        raise SewingOutputError(400, f"Sewing input {next_input} exceeds upstream passed {upstream} for this batch")
    _require_confirmed_cutting_output(cutting_passed, payload.input_qty, payload.sewn_qty,
                                      payload.passed_qty, payload.failed_qty, payload.rejected_qty,
                                      payload.rework_qty)

    record = sewing_output_persistence.insert_sewing_output(db, SewingOutputRecordValues(
        work_order_id=wo.id,
        production_batch_id=batch_id,
        sewing_assignment_id=assignment.id if assignment else None,
        input_qty=payload.input_qty,
        sewn_qty=payload.sewn_qty,
        passed_qty=payload.passed_qty,
        failed_qty=payload.failed_qty,
        rework_qty=payload.rework_qty,
        rejected_qty=payload.rejected_qty,
        size_quantities=sizes,
        defect_reason=payload.defect_reason,
        line_name=payload.line_name,
        operator_id=payload.operator_id or actor.id,
        notes=payload.notes,
    ))
    sync_sewing_input(db, wo)
    passed = int(payload.passed_qty or 0)
    defect_qty = int(payload.failed_qty or 0) + int(payload.rejected_qty or 0)
    consumed_total = passed + defect_qty
    applied = 0
    assignment_quantity = assignment_completed = None
    assignment_status: SewingOutputAssignmentTransitionStatus | None = None
    assignment_start = assignment_end = None
    if assignment and consumed_total > 0:
        assignment_quantity = max(int(assignment.quantity or 0), int(assignment.completed_qty or 0) + consumed_total)
        remaining = max(0, assignment_quantity - int(assignment.completed_qty or 0))
        applied = min(remaining, consumed_total)
        assignment_completed = int(assignment.completed_qty or 0) + applied
        if assignment_completed > 0 and assignment.status == "planned":
            assignment_status = SewingOutputAssignmentTransitionStatus.IN_PROGRESS
            assignment_start = assignment.actual_start or datetime.now(timezone.utc)
        if assignment_completed >= assignment_quantity:
            assignment_completed = assignment_quantity
            assignment_status = SewingOutputAssignmentTransitionStatus.COMPLETED
            assignment_start = assignment.actual_start or datetime.now(timezone.utc)
            assignment_end = datetime.now(timezone.utc)
        elif assignment_status is None:
            assignment_status = (
                SewingOutputAssignmentTransitionStatus.COMPLETED
                if assignment.status == "completed"
                else SewingOutputAssignmentTransitionStatus.IN_PROGRESS
            )
    sewing_output_persistence.apply_sewing_output_accounting(
        row=record, work_order=wo, assignment=assignment,
        accounting=SewingOutputAccounting(
            assignment_applied_qty=applied,
            actual_input_qty=int(wo.actual_input_qty or 0),
            actual_output_qty=int(wo.actual_output_qty or 0) + passed,
            passed_qty=int(wo.passed_qty or 0) + passed,
            failed_qty=int(wo.failed_qty or 0) + defect_qty,
            rework_qty=int(wo.rework_qty or 0) + int(payload.rework_qty or 0),
            assignment_quantity=assignment_quantity,
            assignment_completed_qty=assignment_completed,
            assignment_status=assignment_status,
            assignment_actual_start=assignment_start,
            assignment_actual_end=assignment_end,
        ),
    )
    create_waste_record(
        db, production_order_id=wo.production_order_id, work_order_id=wo.id,
        source_department_id=wo.department_id, item_id=None, batch_id=None,
        waste_type="sewing_defect", quantity=float(defect_qty), unit="pcs",
        reason=payload.defect_reason or "Auto-created from sewing record", created_by=actor.id,
    )
    package_code = sync_packaging_department_for_bundle_route(db, wo.production_order_id, batch_id)
    _raise_output_plans(db, wo)
    advance_workflow(db, wo, trigger_output_qty=passed)
    if passed > 0:
        package_wo = _context_work_order(db, wo, "packaging")
        notify_department(
            db, department_code=package_code, title="Awaiting packaging",
            message=f"Order {wo.order_no or wo.id} has {passed} pcs ready for packaging.",
            link=f"/work-orders/{package_wo.id}/packaging" if package_wo else "/packages",
            exclude_user_id=None,
        )
        # Existing handler does not exclude actor; notification service's default is preserved.
    log_action(db, actor, "create", "SewingRecord", record.id, new_value={
        "work_order_id": wo.id, "production_batch_id": batch_id,
        "input_qty": record.input_qty, "passed_qty": record.passed_qty,
        "size_quantities": sizes,
    })
    store_idempotent_response(db, scope="sewing:output", key=idempotency_key,
                              payload=payload.model_dump(), response={"id": record.id}, user=actor)
    db.commit()
    db.refresh(record)
    return {"id": record.id}

def record_sewing_output(db: Session, *, actor: User, payload: SewingRecordIn,
                         idempotency_key: str | None, band_assignment_id: int | None = None
                         ) -> SewingOutputResult | dict:
    """Run the shared route-neutral operation on the caller's Session."""
    try:
        return _record_sewing_output(
            db, actor=actor, payload=payload, idempotency_key=idempotency_key,
            band_assignment_id=band_assignment_id,
        )
    except SewingOutputError:
        raise
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        detail = getattr(exc, "detail", None)
        if type(status_code) is int and detail is not None:
            raise SewingOutputError(status_code, str(detail)) from exc
        raise
