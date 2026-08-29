"""Cross-department process tracking.

Returns, for every active production order, the current stage of each linked
work order — which department is working on it, how many units are done vs
planned, deadlines, sewing-flow assignment, overdue and block flags.
"""
from datetime import date, datetime, timezone
from fastapi import APIRouter
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser
from app.core.pagination import clamp_pagination
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.models import (
    SalesOrder, ProductionOrder, WorkOrder, Customer, Model, ModelBOM, SewingFlow, SewingAssignment,
    CuttingPassport, CuttingRecord, PrintingRecord, SewingRecord, SewingReplacementRequest,
    PackagingRecord, Package, PackageBatchAllocation, StockBatch, Department, Bundle,
)
from app.core.dt import as_utc, date_filter_bounds
from app.services.bundles import SEWING_FACTORY_CODES, resolve_sewing_factory_code
from app.services.factory_scope import selected_factory_code
from app.services.model_images import material_preview_image_url, model_display_image_url
from app.services.payroll_factory_scope import production_order_factory_condition

router = APIRouter(prefix="/process-tracking", tags=["process-tracking"])
_OP_ORDER = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
_OP_RANK = {op: i for i, op in enumerate(_OP_ORDER)}
_TERMINAL_STATUSES = {"completed", "rejected", "cancelled"}
_STATUS_PRIORITY = [
    "in_progress",
    "collected",
    "ready",
    "pending",
    "paused",
    "waiting",
    "planning",
    "new",
]
_STARTED_STATUSES = {"in_progress", "pending", "collected", "ready"}


def _department_ref(department: Department) -> dict[str, str]:
    return {
        "code": str(department.code or "").strip().upper(),
        "name": str(department.name or department.code or "").strip(),
    }


def _positive_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _actual_output_quantity(stages: list[dict]) -> int:
    """Return the highest verified output reached by any production stage."""
    return max((_positive_int(stage.get("completed")) for stage in stages), default=0)


def _stage_dict(wo, flow, now: datetime, replacement_totals: dict[str, int] | None = None) -> dict:
    deadline_dt = as_utc(wo.deadline)
    status = str(wo.status or "")
    if wo.operation == "storage_transfer" and status in _STARTED_STATUSES:
        moved = sum(
            _positive_int(value)
            for value in (wo.actual_output_qty, wo.passed_qty, wo.failed_qty, wo.rework_qty)
        )
        if moved <= 0:
            status = "waiting"
    overdue = bool(deadline_dt and status not in _TERMINAL_STATUSES and deadline_dt < now)
    planned = int(wo.planned_output_qty or 0)
    passed = int(wo.passed_qty or 0)
    failed = int(wo.failed_qty or 0)
    resolved_failed = 0 if wo.operation == "sewing" else failed
    processed = min(planned, passed + resolved_failed) if planned > 0 else passed + resolved_failed
    pct = round(100.0 * processed / planned, 1) if planned > 0 else 0.0
    replacement_totals = replacement_totals or {}
    has_open_replacements = (
        int(replacement_totals.get("waiting_cutting_qty", 0)) > 0
        if wo.operation == "cutting"
        else int(replacement_totals.get("open_qty", 0)) > 0
        if wo.operation in {"sewing", "packaging", "storage_transfer"}
        else False
    )
    return {
        "work_order_id": wo.id,
        "operation": wo.operation,
        "department_id": wo.department_id,
        "status": status,
        "planned": planned,
        "completed": passed,
        "failed": failed,
        "processed": processed,
        "rework": int(wo.rework_qty or 0),
        "progress_pct": pct,
        "has_open_replacements": has_open_replacements,
        "assigned_to": wo.assigned_to,
        "sewing_flow_id": wo.sewing_flow_id,
        "sewing_flow_code": flow.code if flow else None,
        "sewing_flow_name": flow.name if flow else None,
        "is_blocked": bool(wo.is_blocked),
        "block_reason": wo.block_reason,
        "deadline": deadline_dt,
        "overdue": overdue,
        "start_time": wo.start_time,
        "end_time": wo.end_time,
    }


def _rollup_operation(operation: str, rows: list[dict]) -> dict:
    planned = sum(int(r["planned"] or 0) for r in rows)
    completed = sum(int(r["completed"] or 0) for r in rows)
    failed = sum(int(r["failed"] or 0) for r in rows)
    processed = sum(int(r.get("processed", r["completed"]) or 0) for r in rows)
    rework = sum(int(r["rework"] or 0) for r in rows)
    pct = round(100.0 * processed / planned, 1) if planned > 0 else 0.0

    if rows and all(str(r["status"]) in _TERMINAL_STATUSES for r in rows):
        if all(str(r["status"]) == "completed" for r in rows):
            status = "completed"
        else:
            status = rows[0]["status"]
    else:
        status = next(
            (candidate for candidate in _STATUS_PRIORITY if any(str(r["status"]) == candidate for r in rows)),
            rows[0]["status"] if rows else "waiting",
        )

    blocked = next((r for r in rows if r.get("is_blocked")), None)
    deadlines = [as_utc(r.get("deadline")) for r in rows if r.get("deadline")]
    deadline = min(deadlines) if deadlines else None
    overdue = any(bool(r.get("overdue")) for r in rows)

    flow_codes = {str(r["sewing_flow_code"]) for r in rows if r.get("sewing_flow_code")}
    flow_code = next(iter(flow_codes)) if len(flow_codes) == 1 else None
    flow_name = None

    return {
        "work_order_id": rows[0]["work_order_id"] if rows else 0,
        "operation": operation,
        "department_id": rows[0]["department_id"] if rows else None,
        "status": status,
        "planned": planned,
        "completed": completed,
        "failed": failed,
        "processed": processed,
        "rework": rework,
        "progress_pct": pct,
        "has_open_replacements": any(bool(r.get("has_open_replacements")) for r in rows),
        "assigned_to": None,
        "sewing_flow_id": None,
        "sewing_flow_code": flow_code,
        "sewing_flow_name": flow_name,
        "is_blocked": blocked is not None,
        "block_reason": blocked.get("block_reason") if blocked else None,
        "deadline": deadline,
        "overdue": overdue,
        "start_time": None,
        "end_time": None,
    }


def _batch_stage_status(base_status: str, planned: int, completed: int, activity: int) -> str:
    if base_status in ("cancelled", "rejected"):
        return base_status
    if planned > 0 and completed >= planned:
        return "completed"
    if activity > 0 or completed > 0:
        return "in_progress"
    return "waiting"


def _stage_has_started(stage: dict) -> bool:
    status = str(stage.get("status") or "")
    if str(stage.get("operation") or "") == "storage_transfer":
        return _positive_int(stage.get("completed")) > 0
    if status in _STARTED_STATUSES:
        return True
    for key in ("completed", "failed", "rework"):
        try:
            if int(stage.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _apply_upstream_loss_progress(stages: list[dict]) -> None:
    upstream_failed = 0
    for stage in sorted(stages, key=lambda s: (_OP_RANK.get(str(s.get("operation")), 999), int(s.get("work_order_id") or 0))):
        operation = str(stage.get("operation") or "")
        planned = max(0, int(stage.get("planned") or 0))
        completed = max(0, int(stage.get("completed") or 0))
        failed = max(0, int(stage.get("failed") or 0))
        resolved_failed = 0 if operation == "sewing" else failed
        processed = completed + resolved_failed + upstream_failed
        if planned > 0:
            processed = min(planned, processed)
            stage["progress_pct"] = round(100.0 * processed / planned, 1)
            if (
                processed >= planned
                and not stage.get("has_open_replacements")
                and str(stage.get("status") or "") not in ("cancelled", "rejected")
            ):
                stage["status"] = "completed"
        else:
            stage["progress_pct"] = 0.0
        stage["processed"] = processed
        upstream_failed += resolved_failed


def _internal_batch_stage_rows(db, po: ProductionOrder, base_stages: list[dict]) -> dict[int, list[dict]]:
    """Build per-batch progress for POs that keep one WO per operation.

    In this mode the WO counters are intentionally total-order counters. Batch
    progress comes from operation records carrying production_batch_id.
    """
    batches = list(po.batches or [])
    if not batches or not base_stages:
        return {}

    batch_ids = {int(b.id) for b in batches}
    wo_ids_by_op: dict[str, list[int]] = {}
    for wo in po.work_orders:
        if wo.operation in _OP_ORDER:
            wo_ids_by_op.setdefault(str(wo.operation), []).append(int(wo.id))

    totals: dict[tuple[int, str], dict[str, int]] = {}

    def add_total(
        batch_id,
        operation: str,
        *,
        completed: int = 0,
        failed: int = 0,
        rework: int = 0,
        activity: int = 0,
    ) -> None:
        if batch_id is None:
            return
        bid = int(batch_id)
        if bid not in batch_ids:
            return
        row = totals.setdefault((bid, operation), {"completed": 0, "failed": 0, "rework": 0, "activity": 0})
        row["completed"] += int(completed or 0)
        row["failed"] += int(failed or 0)
        row["rework"] += int(rework or 0)
        row["activity"] += int(activity or 0)

    cutting_ids = wo_ids_by_op.get("cutting", [])
    if cutting_ids:
        for batch_id, cut_sum, passed_sum, defective_sum in (
            db.query(
                CuttingRecord.production_batch_id,
                func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
                func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
                func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
            )
            .filter(CuttingRecord.work_order_id.in_(cutting_ids))
            .group_by(CuttingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "cutting",
                completed=int(passed_sum or 0),
                failed=int(defective_sum or 0),
                activity=int(cut_sum or 0) + int(passed_sum or 0) + int(defective_sum or 0),
            )

    printing_ids = wo_ids_by_op.get("printing", [])
    if printing_ids:
        for batch_id, input_sum, printed_sum, passed_sum, rejected_sum in (
            db.query(
                PrintingRecord.production_batch_id,
                func.coalesce(func.sum(PrintingRecord.input_qty), 0),
                func.coalesce(func.sum(PrintingRecord.printed_qty), 0),
                func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
                func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
            )
            .filter(PrintingRecord.work_order_id.in_(printing_ids))
            .group_by(PrintingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "printing",
                completed=int(passed_sum or 0),
                failed=int(rejected_sum or 0),
                activity=int(input_sum or 0) + int(printed_sum or 0) + int(passed_sum or 0) + int(rejected_sum or 0),
            )

    sewing_ids = wo_ids_by_op.get("sewing", [])
    if sewing_ids:
        for batch_id, input_sum, sewn_sum, passed_sum, failed_sum, rework_sum, rejected_sum in (
            db.query(
                SewingRecord.production_batch_id,
                func.coalesce(func.sum(SewingRecord.input_qty), 0),
                func.coalesce(func.sum(SewingRecord.sewn_qty), 0),
                func.coalesce(func.sum(SewingRecord.passed_qty), 0),
                func.coalesce(func.sum(SewingRecord.failed_qty), 0),
                func.coalesce(func.sum(SewingRecord.rework_qty), 0),
                func.coalesce(func.sum(SewingRecord.rejected_qty), 0),
            )
            .filter(SewingRecord.work_order_id.in_(sewing_ids))
            .group_by(SewingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "sewing",
                completed=int(passed_sum or 0),
                failed=int(failed_sum or 0),
                rework=int(rework_sum or 0),
                activity=(
                    int(input_sum or 0)
                    + int(sewn_sum or 0)
                    + int(passed_sum or 0)
                    + int(failed_sum or 0)
                    + int(rework_sum or 0)
                    + int(rejected_sum or 0)
                ),
            )

    packaging_ids = wo_ids_by_op.get("packaging", [])
    if packaging_ids:
        for batch_id, input_sum, packed_sum, damaged_sum in (
            db.query(
                PackagingRecord.production_batch_id,
                func.coalesce(func.sum(PackagingRecord.input_qty), 0),
                func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
                func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
            )
            .filter(PackagingRecord.work_order_id.in_(packaging_ids))
            .group_by(PackagingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "packaging",
                completed=int(packed_sum or 0),
                failed=int(damaged_sum or 0),
                activity=int(input_sum or 0) + int(packed_sum or 0) + int(damaged_sum or 0),
            )

    storage_ids = wo_ids_by_op.get("storage_transfer", [])
    if storage_ids:
        storage_statuses = ["received_in_storage", "reserved", "shipped", "delivered"]
        direct_storage_by_batch: dict[int, int] = {}
        allocated_package_ids: set[int] = set()
        for package_id, batch_id, received_sum in (
            db.query(
                PackageBatchAllocation.package_id,
                PackageBatchAllocation.production_batch_id,
                func.coalesce(func.sum(PackageBatchAllocation.quantity), 0),
            )
            .join(Package, Package.id == PackageBatchAllocation.package_id)
            .filter(
                Package.production_order_id == po.id,
                PackageBatchAllocation.production_batch_id.in_(batch_ids),
                Package.status.in_(storage_statuses),
            )
            .group_by(PackageBatchAllocation.package_id, PackageBatchAllocation.production_batch_id)
            .all()
        ):
            allocated_package_ids.add(int(package_id))
            qty = int(received_sum or 0)
            direct_storage_by_batch[int(batch_id)] = direct_storage_by_batch.get(int(batch_id), 0) + qty
            add_total(batch_id, "storage_transfer", completed=qty, activity=qty)

        fallback_qry = (
            db.query(
                Package.production_batch_id,
                func.coalesce(func.sum(Package.total_quantity), 0),
            )
            .filter(
                Package.production_order_id == po.id,
                Package.production_batch_id.in_(batch_ids),
                Package.status.in_(storage_statuses),
            )
        )
        if allocated_package_ids:
            fallback_qry = fallback_qry.filter(~Package.id.in_(allocated_package_ids))
        for batch_id, received_sum in fallback_qry.group_by(Package.production_batch_id).all():
            if batch_id is None:
                continue
            qty = int(received_sum or 0)
            direct_storage_by_batch[int(batch_id)] = direct_storage_by_batch.get(int(batch_id), 0) + qty
            add_total(batch_id, "storage_transfer", completed=qty, activity=qty)

        unassigned_qry = db.query(func.coalesce(func.sum(Package.total_quantity), 0)).filter(
            Package.production_order_id == po.id,
            Package.production_batch_id.is_(None),
            Package.status.in_(storage_statuses),
        )
        if allocated_package_ids:
            unassigned_qry = unassigned_qry.filter(~Package.id.in_(allocated_package_ids))
        unassigned_received = int(unassigned_qry.scalar() or 0)
        if unassigned_received > 0:
            remaining = unassigned_received
            for b in sorted(batches, key=lambda x: (int(x.batch_index or 0), int(x.id or 0))):
                if remaining <= 0:
                    break
                bid = int(b.id)
                planned_qty = max(0, int(b.planned_quantity or 0))
                packaged_qty = int(totals.get((bid, "packaging"), {}).get("completed", 0))
                capacity = packaged_qty if packaged_qty > 0 else planned_qty
                if planned_qty > 0:
                    capacity = min(capacity, planned_qty)
                capacity = max(0, capacity - int(direct_storage_by_batch.get(bid, 0)))
                if capacity <= 0:
                    continue
                take = min(remaining, capacity)
                add_total(bid, "storage_transfer", completed=take, activity=take)
                remaining -= take

    base_by_op = {str(s["operation"]): s for s in base_stages}
    out: dict[int, list[dict]] = {}
    for b in sorted(batches, key=lambda x: (int(x.batch_index or 0), int(x.id or 0))):
        planned = int(b.planned_quantity or 0)
        rows: list[dict] = []
        for op in _OP_ORDER:
            base = base_by_op.get(op)
            if not base:
                continue
            total = totals.get((int(b.id), op), {})
            completed = int(total.get("completed", 0))
            failed = int(total.get("failed", 0))
            activity = int(total.get("activity", 0))
            row = dict(base)
            row["planned"] = planned
            row["completed"] = completed
            row["failed"] = failed
            row["processed"] = completed + (0 if op == "sewing" else failed)
            row["rework"] = int(total.get("rework", 0))
            row["progress_pct"] = round(100.0 * int(row["processed"]) / planned, 1) if planned > 0 else 0.0
            row["status"] = _batch_stage_status(str(base.get("status") or "waiting"), planned, int(row["processed"]), activity)
            rows.append(row)
        _apply_upstream_loss_progress(rows)
        out[int(b.id)] = rows
    return out


def _bulk_internal_batch_evidence(
    db,
    production_orders: list[ProductionOrder],
) -> dict[int, dict[tuple[int, str], dict[str, int]]]:
    """Load internal-batch operation evidence for the whole page.

    The previous serializer executed five to eight aggregate statements per
    production order. This keeps the exact calculation but groups each source
    once for all orders in the bounded page.
    """
    internal_orders = [
        po
        for po in production_orders
        if po.batches and all(wo.production_batch_id is None for wo in po.work_orders)
    ]
    if not internal_orders:
        return {}

    order_ids = {int(po.id) for po in internal_orders}
    batch_to_order = {
        int(batch.id): int(po.id)
        for po in internal_orders
        for batch in po.batches
    }
    all_batch_ids = set(batch_to_order)
    work_order_ids_by_operation: dict[str, set[int]] = {}
    for po in internal_orders:
        for wo in po.work_orders:
            if wo.operation in _OP_ORDER:
                work_order_ids_by_operation.setdefault(str(wo.operation), set()).add(int(wo.id))

    totals_by_order: dict[int, dict[tuple[int, str], dict[str, int]]] = {
        order_id: {} for order_id in order_ids
    }

    def add_total(
        batch_id,
        operation: str,
        *,
        completed: int = 0,
        failed: int = 0,
        rework: int = 0,
        activity: int = 0,
    ) -> None:
        if batch_id is None:
            return
        bid = int(batch_id)
        order_id = batch_to_order.get(bid)
        if order_id is None:
            return
        row = totals_by_order[order_id].setdefault(
            (bid, operation),
            {"completed": 0, "failed": 0, "rework": 0, "activity": 0},
        )
        row["completed"] += int(completed or 0)
        row["failed"] += int(failed or 0)
        row["rework"] += int(rework or 0)
        row["activity"] += int(activity or 0)

    cutting_ids = work_order_ids_by_operation.get("cutting", set())
    if cutting_ids:
        for batch_id, cut_sum, passed_sum, defective_sum in (
            db.query(
                CuttingRecord.production_batch_id,
                func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
                func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
                func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
            )
            .filter(CuttingRecord.work_order_id.in_(cutting_ids))
            .group_by(CuttingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "cutting",
                completed=int(passed_sum or 0),
                failed=int(defective_sum or 0),
                activity=int(cut_sum or 0) + int(passed_sum or 0) + int(defective_sum or 0),
            )

    printing_ids = work_order_ids_by_operation.get("printing", set())
    if printing_ids:
        for batch_id, input_sum, printed_sum, passed_sum, rejected_sum in (
            db.query(
                PrintingRecord.production_batch_id,
                func.coalesce(func.sum(PrintingRecord.input_qty), 0),
                func.coalesce(func.sum(PrintingRecord.printed_qty), 0),
                func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
                func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
            )
            .filter(PrintingRecord.work_order_id.in_(printing_ids))
            .group_by(PrintingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "printing",
                completed=int(passed_sum or 0),
                failed=int(rejected_sum or 0),
                activity=int(input_sum or 0) + int(printed_sum or 0) + int(passed_sum or 0) + int(rejected_sum or 0),
            )

    sewing_ids = work_order_ids_by_operation.get("sewing", set())
    if sewing_ids:
        for batch_id, input_sum, sewn_sum, passed_sum, failed_sum, rework_sum, rejected_sum in (
            db.query(
                SewingRecord.production_batch_id,
                func.coalesce(func.sum(SewingRecord.input_qty), 0),
                func.coalesce(func.sum(SewingRecord.sewn_qty), 0),
                func.coalesce(func.sum(SewingRecord.passed_qty), 0),
                func.coalesce(func.sum(SewingRecord.failed_qty), 0),
                func.coalesce(func.sum(SewingRecord.rework_qty), 0),
                func.coalesce(func.sum(SewingRecord.rejected_qty), 0),
            )
            .filter(SewingRecord.work_order_id.in_(sewing_ids))
            .group_by(SewingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "sewing",
                completed=int(passed_sum or 0),
                failed=int(failed_sum or 0),
                rework=int(rework_sum or 0),
                activity=sum(int(value or 0) for value in (
                    input_sum, sewn_sum, passed_sum, failed_sum, rework_sum, rejected_sum
                )),
            )

    packaging_ids = work_order_ids_by_operation.get("packaging", set())
    if packaging_ids:
        for batch_id, input_sum, packed_sum, damaged_sum in (
            db.query(
                PackagingRecord.production_batch_id,
                func.coalesce(func.sum(PackagingRecord.input_qty), 0),
                func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
                func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
            )
            .filter(PackagingRecord.work_order_id.in_(packaging_ids))
            .group_by(PackagingRecord.production_batch_id)
            .all()
        ):
            add_total(
                batch_id,
                "packaging",
                completed=int(packed_sum or 0),
                failed=int(damaged_sum or 0),
                activity=int(input_sum or 0) + int(packed_sum or 0) + int(damaged_sum or 0),
            )

    if work_order_ids_by_operation.get("storage_transfer"):
        storage_statuses = ["received_in_storage", "reserved", "shipped", "delivered"]
        allocated_package_ids: set[int] = set()
        direct_storage_by_batch: dict[int, int] = {}
        allocation_rows = (
            db.query(
                PackageBatchAllocation.package_id,
                PackageBatchAllocation.production_batch_id,
                func.coalesce(func.sum(PackageBatchAllocation.quantity), 0),
            )
            .join(Package, Package.id == PackageBatchAllocation.package_id)
            .filter(
                Package.production_order_id.in_(order_ids),
                PackageBatchAllocation.production_batch_id.in_(all_batch_ids),
                Package.status.in_(storage_statuses),
            )
            .group_by(PackageBatchAllocation.package_id, PackageBatchAllocation.production_batch_id)
            .all()
        )
        for package_id, batch_id, received_sum in allocation_rows:
            allocated_package_ids.add(int(package_id))
            qty = int(received_sum or 0)
            bid = int(batch_id)
            direct_storage_by_batch[bid] = direct_storage_by_batch.get(bid, 0) + qty
            add_total(bid, "storage_transfer", completed=qty, activity=qty)

        fallback_qry = db.query(
            Package.production_batch_id,
            func.coalesce(func.sum(Package.total_quantity), 0),
        ).filter(
            Package.production_order_id.in_(order_ids),
            Package.production_batch_id.in_(all_batch_ids),
            Package.status.in_(storage_statuses),
        )
        if allocated_package_ids:
            fallback_qry = fallback_qry.filter(~Package.id.in_(allocated_package_ids))
        for batch_id, received_sum in fallback_qry.group_by(Package.production_batch_id).all():
            qty = int(received_sum or 0)
            bid = int(batch_id)
            direct_storage_by_batch[bid] = direct_storage_by_batch.get(bid, 0) + qty
            add_total(bid, "storage_transfer", completed=qty, activity=qty)

        unassigned_qry = db.query(
            Package.production_order_id,
            func.coalesce(func.sum(Package.total_quantity), 0),
        ).filter(
            Package.production_order_id.in_(order_ids),
            Package.production_batch_id.is_(None),
            Package.status.in_(storage_statuses),
        )
        if allocated_package_ids:
            unassigned_qry = unassigned_qry.filter(~Package.id.in_(allocated_package_ids))
        unassigned_by_order = {
            int(order_id): int(quantity or 0)
            for order_id, quantity in unassigned_qry.group_by(Package.production_order_id).all()
        }
        for po in internal_orders:
            remaining = unassigned_by_order.get(int(po.id), 0)
            for batch in sorted(po.batches, key=lambda row: (int(row.batch_index or 0), int(row.id or 0))):
                if remaining <= 0:
                    break
                bid = int(batch.id)
                planned_qty = max(0, int(batch.planned_quantity or 0))
                packaged_qty = int(totals_by_order[int(po.id)].get((bid, "packaging"), {}).get("completed", 0))
                capacity = packaged_qty if packaged_qty > 0 else planned_qty
                if planned_qty > 0:
                    capacity = min(capacity, planned_qty)
                capacity = max(0, capacity - direct_storage_by_batch.get(bid, 0))
                take = min(remaining, capacity)
                if take > 0:
                    add_total(bid, "storage_transfer", completed=take, activity=take)
                    remaining -= take

    return totals_by_order


def _internal_batch_stage_rows_from_totals(
    po: ProductionOrder,
    base_stages: list[dict],
    totals: dict[tuple[int, str], dict[str, int]],
) -> dict[int, list[dict]]:
    base_by_op = {str(stage["operation"]): stage for stage in base_stages}
    out: dict[int, list[dict]] = {}
    for batch in sorted(po.batches, key=lambda row: (int(row.batch_index or 0), int(row.id or 0))):
        planned = int(batch.planned_quantity or 0)
        rows: list[dict] = []
        for operation in _OP_ORDER:
            base = base_by_op.get(operation)
            if not base:
                continue
            total = totals.get((int(batch.id), operation), {})
            completed = int(total.get("completed", 0))
            failed = int(total.get("failed", 0))
            activity = int(total.get("activity", 0))
            row = dict(base)
            row["planned"] = planned
            row["completed"] = completed
            row["failed"] = failed
            row["processed"] = completed + (0 if operation == "sewing" else failed)
            row["rework"] = int(total.get("rework", 0))
            row["progress_pct"] = round(100.0 * int(row["processed"]) / planned, 1) if planned > 0 else 0.0
            row["status"] = _batch_stage_status(
                str(base.get("status") or "waiting"),
                planned,
                int(row["processed"]),
                activity,
            )
            rows.append(row)
        _apply_upstream_loss_progress(rows)
        out[int(batch.id)] = rows
    return out


def _process_summary(stages: list[dict], po_status: str) -> dict:
    blocked = next((s for s in stages if s.get("is_blocked")), None)
    if not stages:
        current_stage_label = "planning_required"
        current_stage_status = po_status
        current_stage = None
    else:
        active_stages = [s for s in stages if str(s.get("status")) not in _TERMINAL_STATUSES]
        if not active_stages:
            current_stage = None
        else:
            started_stages = [s for s in active_stages if _stage_has_started(s)]
            if started_stages:
                current_stage = max(
                    started_stages,
                    key=lambda s: (_OP_RANK.get(str(s.get("operation")), -1), int(s.get("work_order_id") or 0)),
                )
            else:
                current_stage = min(
                    active_stages,
                    key=lambda s: (_OP_RANK.get(str(s.get("operation")), 999), int(s.get("work_order_id") or 0)),
                )

    if stages and current_stage is None:
        current_stage_label = "completed"
        current_stage_status = None
    elif current_stage is not None:
        current_stage_label = current_stage["operation"]
        current_stage_status = current_stage["status"]

    return {
        "current_stage": current_stage_label,
        "current_stage_status": current_stage_status,
        "current_sewing_flow": current_stage["sewing_flow_code"] if current_stage else None,
        "is_blocked": blocked is not None,
        "blocked_by": {
            "work_order_id": blocked["work_order_id"],
            "operation": blocked["operation"],
            "reason": blocked["block_reason"],
        } if blocked else None,
    }


@router.get("")
def list_processes(
    db: DbSession, current: CurrentUser,
    status: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    sort: str = "created_desc",
    only_active: bool = True,
    sewing_completed_only: bool = False,
    page: int = 1,
    page_size: int = 100,
    include_total: bool = False,
):
    """One row per Production Order with rolled-up stage progress.

    Uses bulk lookups for Model / SalesOrder / Customer / SewingFlow to avoid
    N+1 queries when there are many production orders.
    """
    qry = db.query(ProductionOrder).options(
        selectinload(ProductionOrder.batches),
        selectinload(ProductionOrder.work_orders),
        selectinload(ProductionOrder.items),
    ).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id,
    ).outerjoin(
        Customer, Customer.id == SalesOrder.customer_id,
    ).outerjoin(
        Model, Model.id == ProductionOrder.model_id,
    ).filter(ProductionOrder.source_type == "standard")
    if status:
        qry = qry.filter(ProductionOrder.status == status)
    if only_active:
        qry = qry.filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))
    if sewing_completed_only:
        # Process QR labels are created only after the sewing team explicitly
        # closes every sewing work order. Do not infer closure from cutting,
        # plans, or downstream stage progress.
        qry = qry.filter(
            production_order_factory_condition(selected_factory_code(current)),
            ProductionOrder.work_orders.any(WorkOrder.operation == "sewing"),
            ~ProductionOrder.work_orders.any(and_(
                WorkOrder.operation == "sewing",
                WorkOrder.status != "completed",
            )),
        )
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(ProductionOrder.created_at >= start)
    if end:
        qry = qry.filter(ProductionOrder.created_at <= end)
    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        model_code_like = normalized_model_code_pattern(search)
        qry = qry.filter(or_(
            ProductionOrder.production_no.ilike(like),
            ProductionOrder.production_type.ilike(like),
            ProductionOrder.status.ilike(like),
            SalesOrder.order_no.ilike(like),
            Customer.name.ilike(like),
            normalized_model_code_column(Model.code).ilike(model_code_like),
            Model.name.ilike(like),
        ))

    safe_page, safe_size, offset = clamp_pagination(page, page_size, max_page_size=100)
    total = qry.count() if include_total else 0
    sort_map = {
        "created_asc": ProductionOrder.id.asc(),
        "created_desc": ProductionOrder.id.desc(),
        "deadline_asc": ProductionOrder.deadline.asc(),
        "deadline_desc": ProductionOrder.deadline.desc(),
        "production_no_asc": ProductionOrder.production_no.asc(),
        "production_no_desc": ProductionOrder.production_no.desc(),
        "status_asc": ProductionOrder.status.asc(),
        "status_desc": ProductionOrder.status.desc(),
    }
    order_clause = sort_map.get((sort or "").strip().lower(), ProductionOrder.id.desc())
    pos = qry.order_by(order_clause, ProductionOrder.id.desc()).offset(offset).limit(safe_size).all()

    # Bulk-load related entities so we resolve names without N+1 queries.
    production_order_ids = {int(p.id) for p in pos}
    model_ids = {p.model_id for p in pos if p.model_id}
    fabric_batch_ids = {p.fabric_batch_id for p in pos if p.fabric_batch_id}
    so_ids = {p.sales_order_id for p in pos if p.sales_order_id}
    work_order_ids = {int(w.id) for p in pos for w in p.work_orders if w.id}
    assignment_rows = (
        db.query(SewingAssignment)
        .filter(
            SewingAssignment.work_order_id.in_(work_order_ids),
            SewingAssignment.status.not_in(["cancelled", "transferred"]),
        )
        .all()
        if work_order_ids
        else []
    )
    assignments_by_wo: dict[int, list[SewingAssignment]] = {}
    for assignment in assignment_rows:
        assignments_by_wo.setdefault(int(assignment.work_order_id), []).append(assignment)

    flow_ids = {w.sewing_flow_id for p in pos for w in p.work_orders if w.sewing_flow_id}
    flow_ids.update({a.sewing_flow_id for a in assignment_rows if a.sewing_flow_id})
    department_ids = {w.department_id for p in pos for w in p.work_orders if w.department_id}
    bundle_factory_rows = (
        db.query(Bundle.production_order_id, Bundle.sewing_factory_code)
        .filter(
            Bundle.production_order_id.in_(production_order_ids),
            Bundle.sewing_factory_code.isnot(None),
            Bundle.status != "cancelled",
        )
        .distinct()
        .all()
        if production_order_ids
        else []
    )
    bundle_factory_codes_by_order: dict[int, set[str]] = {}
    for production_order_id, factory_code in bundle_factory_rows:
        bundle_factory_codes_by_order.setdefault(int(production_order_id), set()).add(
            resolve_sewing_factory_code(factory_code)
        )
    routed_factory_codes = {
        factory_code
        for codes in bundle_factory_codes_by_order.values()
        for factory_code in codes
    }
    lookup_department_codes = routed_factory_codes | (set(SEWING_FACTORY_CODES) if pos else set())
    department_query = db.query(Department)
    if department_ids and lookup_department_codes:
        department_query = department_query.filter(or_(
            Department.id.in_(department_ids),
            Department.code.in_(lookup_department_codes),
        ))
    elif department_ids:
        department_query = department_query.filter(Department.id.in_(department_ids))
    elif lookup_department_codes:
        department_query = department_query.filter(Department.code.in_(lookup_department_codes))
    else:
        department_query = None
    departments = department_query.all() if department_query is not None else []
    departments_by_id = {int(department.id): department for department in departments}
    departments_by_code = {
        str(department.code or "").strip().upper(): department
        for department in departments
    }

    models = {
        m.id: m
        for m in (
            db.query(Model)
            .options(
                selectinload(Model.images),
                selectinload(Model.bom).joinedload(ModelBOM.item),
                selectinload(Model.bom).joinedload(ModelBOM.stock_batch),
            )
            .filter(Model.id.in_(model_ids))
            .all()
            if model_ids
            else []
        )
    }
    fabric_batches = {
        batch.id: batch
        for batch in (
            db.query(StockBatch).filter(StockBatch.id.in_(fabric_batch_ids)).all()
            if fabric_batch_ids
            else []
        )
    }
    sos = {s.id: s for s in (db.query(SalesOrder).filter(SalesOrder.id.in_(so_ids)).all() if so_ids else [])}
    customer_ids = {s.customer_id for s in sos.values() if s.customer_id}
    customers = {c.id: c for c in (db.query(Customer).filter(Customer.id.in_(customer_ids)).all() if customer_ids else [])}
    flows = {f.id: f for f in (db.query(SewingFlow).filter(SewingFlow.id.in_(flow_ids)).all() if flow_ids else [])}
    passports_by_order: dict[int, list[CuttingPassport]] = {}
    passport_rows = (
        db.query(CuttingPassport)
        .filter(CuttingPassport.production_order_id.in_(production_order_ids))
        .order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
        .all()
        if production_order_ids
        else []
    )
    for passport in passport_rows:
        passports_by_order.setdefault(int(passport.production_order_id), []).append(passport)

    replacement_totals_by_order: dict[int, dict[str, int]] = {}
    replacement_rows = (
        db.query(
            SewingReplacementRequest.production_order_id,
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.cut_qty), 0),
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.replaced_qty), 0),
        )
        .filter(SewingReplacementRequest.production_order_id.in_(production_order_ids))
        .group_by(SewingReplacementRequest.production_order_id)
        .all()
        if production_order_ids
        else []
    )
    for production_order_id, waiting_cutting_qty, open_qty in replacement_rows:
        replacement_totals_by_order[int(production_order_id)] = {
            "waiting_cutting_qty": max(0, int(waiting_cutting_qty or 0)),
            "open_qty": max(0, int(open_qty or 0)),
        }

    sewing_output_by_order: dict[int, dict] = {}
    sewing_output_by_batch: dict[tuple[int, int], dict] = {}
    if sewing_completed_only and production_order_ids:
        sewing_rows = (
            db.query(
                WorkOrder.production_order_id,
                SewingRecord.production_batch_id,
                SewingRecord.passed_qty,
                SewingRecord.size_quantities,
            )
            .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
            .filter(
                WorkOrder.operation == "sewing",
                WorkOrder.production_order_id.in_(production_order_ids),
            )
            .order_by(SewingRecord.id)
            .all()
        )

        def add_sewing_output(bucket: dict, passed_qty: int, size_quantities) -> None:
            bucket["completed_quantity"] = int(bucket.get("completed_quantity", 0)) + _positive_int(passed_qty)
            sizes = bucket.setdefault("sizes", {})
            allocated = 0
            for size_row in size_quantities or []:
                size = str((size_row or {}).get("size") or "").strip()
                quantity = _positive_int((size_row or {}).get("quantity"))
                if not size or quantity <= 0:
                    continue
                key = size.casefold()
                current = sizes.setdefault(key, {"size": size, "completed_quantity": 0})
                current["completed_quantity"] += quantity
                allocated += quantity
            bucket["allocated_quantity"] = int(bucket.get("allocated_quantity", 0)) + allocated

        for production_order_id, production_batch_id, passed_qty, size_quantities in sewing_rows:
            order_id = int(production_order_id)
            add_sewing_output(
                sewing_output_by_order.setdefault(order_id, {}),
                passed_qty,
                size_quantities,
            )
            if production_batch_id is not None:
                add_sewing_output(
                    sewing_output_by_batch.setdefault((order_id, int(production_batch_id)), {}),
                    passed_qty,
                    size_quantities,
                )

    internal_batch_totals_by_order = _bulk_internal_batch_evidence(db, pos)
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for po in pos:
        model = models.get(po.model_id)
        fabric_batch = fabric_batches.get(po.fabric_batch_id)
        so = sos.get(po.sales_order_id) if po.sales_order_id else None
        customer = customers.get(so.customer_id) if so and so.customer_id else None
        cutting_passports = passports_by_order.get(int(po.id), [])
        cutting_departments = {
            str(department.code or "").strip().upper(): department
            for wo in po.work_orders
            if wo.operation == "cutting"
            for department in [departments_by_id.get(int(wo.department_id)) if wo.department_id else None]
            if department is not None
        }
        sewing_factory_codes = bundle_factory_codes_by_order.get(int(po.id), set())
        if not sewing_factory_codes:
            sewing_factory_codes = {
                resolve_sewing_factory_code(department.code)
                for wo in po.work_orders
                if wo.operation == "sewing"
                for department in [departments_by_id.get(int(wo.department_id)) if wo.department_id else None]
                if department is not None
            }
        sewing_factories = {
            factory_code: departments_by_code[factory_code]
            for factory_code in sewing_factory_codes
            if factory_code in departments_by_code
        }
        sewing_output = sewing_output_by_order.get(int(po.id), {})

        by_batch: dict[int | None, list[dict]] = {}
        all_stage_rows: list[dict] = []
        for wo in po.work_orders:
            flow = flows.get(wo.sewing_flow_id) if wo.sewing_flow_id else None
            stage = _stage_dict(wo, flow, now, replacement_totals_by_order.get(int(po.id)))
            assigned_flows = [
                flows.get(a.sewing_flow_id)
                for a in assignments_by_wo.get(int(wo.id), [])
                if flows.get(a.sewing_flow_id)
            ]
            if wo.operation == "sewing" and assigned_flows:
                labels = [f"{f.code} / {f.name}" for f in assigned_flows]
                stage["sewing_flow_id"] = assigned_flows[0].id
                stage["sewing_flow_code"] = ", ".join(labels)
                stage["sewing_flow_name"] = ", ".join(f.name for f in assigned_flows)
            by_batch.setdefault(wo.production_batch_id, []).append(stage)
            all_stage_rows.append(stage)

        for batch_stages in by_batch.values():
            batch_stages.sort(key=lambda s: (_OP_RANK.get(str(s.get("operation")), 999), int(s.get("work_order_id") or 0)))
            _apply_upstream_loss_progress(batch_stages)

        by_op: dict[str, list[dict]] = {}
        for s in all_stage_rows:
            by_op.setdefault(str(s["operation"]), []).append(s)
        stages: list[dict] = []
        for op in _OP_ORDER:
            rows = by_op.get(op, [])
            if rows:
                stages.append(_rollup_operation(op, rows))
        _apply_upstream_loss_progress(stages)
        summary = _process_summary(stages, po.status)
        internal_batch_mode = bool(po.batches) and all(w.production_batch_id is None for w in po.work_orders)
        internal_batch_stages = (
            _internal_batch_stage_rows_from_totals(
                po,
                stages,
                internal_batch_totals_by_order.get(int(po.id), {}),
            )
            if internal_batch_mode
            else {}
        )

        batches_out: list[dict] = []
        for b in sorted(po.batches, key=lambda x: (int(x.batch_index or 0), int(x.id or 0))):
            batch_stages = internal_batch_stages.get(int(b.id), []) if internal_batch_mode else by_batch.get(b.id, [])
            batch_summary = _process_summary(batch_stages, po.status)
            batch_sewing_output = sewing_output_by_batch.get((int(po.id), int(b.id)), {})
            batches_out.append({
                "id": b.id,
                "batch_no": b.batch_no,
                "batch_index": b.batch_index,
                "name": b.name,
                "planned_quantity": b.planned_quantity,
                "actual_quantity": _actual_output_quantity(batch_stages),
                **({
                    "sewing_completed_quantity": int(batch_sewing_output.get("completed_quantity", 0)),
                    "sewing_unallocated_quantity": max(
                        0,
                        int(batch_sewing_output.get("completed_quantity", 0))
                        - int(batch_sewing_output.get("allocated_quantity", 0)),
                    ),
                    "sewing_sizes": [
                        {
                            "size": row["size"],
                            "completed_quantity": int(row["completed_quantity"]),
                            "sewing_completed_quantity": int(row["completed_quantity"]),
                        }
                        for row in batch_sewing_output.get("sizes", {}).values()
                    ],
                } if sewing_completed_only else {}),
                "start_date": b.start_date,
                "deadline": b.deadline,
                "notes": b.notes,
                "current_stage": batch_summary["current_stage"],
                "current_stage_status": batch_summary["current_stage_status"],
                "current_sewing_flow": batch_summary["current_sewing_flow"],
                "is_blocked": batch_summary["is_blocked"],
                "blocked_by": batch_summary["blocked_by"],
                "stages": batch_stages,
            })

        po_deadline_utc = as_utc(po.deadline)
        po_overdue = bool(po_deadline_utc and po.status not in ("delivered", "closed", "cancelled") and po_deadline_utc < now)
        size_totals: dict[str, dict] = {}
        for item in po.items:
            size = str(item.size or "").strip() or "-"
            size_key = size.casefold()
            bucket = size_totals.setdefault(
                size_key,
                {"size": size, "planned_quantity": 0, "completed_quantity": 0},
            )
            bucket["planned_quantity"] += int(item.planned_quantity or 0)
            bucket["completed_quantity"] += int(item.completed_quantity or 0)
        if sewing_completed_only:
            for size_key, sewing_size in sewing_output.get("sizes", {}).items():
                size_totals.setdefault(
                    size_key,
                    {"planned_quantity": 0, "completed_quantity": 0, "size": sewing_size["size"]},
                )

        out.append({
            "production_order_id": po.id,
            "production_no": po.production_no,
            "order_no": po.order_no,
            "production_type": po.production_type,
            "po_status": po.status,
            "po_deadline": po.deadline,
            "po_overdue": po_overdue,
            "planned_quantity": po.planned_quantity,
            "actual_quantity": _actual_output_quantity(stages),
            **({
                "sewing_completed_quantity": int(sewing_output.get("completed_quantity", 0)),
                "sewing_unallocated_quantity": max(
                    0,
                    int(sewing_output.get("completed_quantity", 0))
                    - int(sewing_output.get("allocated_quantity", 0)),
                ),
            } if sewing_completed_only else {}),
            "sales_order_id": po.sales_order_id,
            "sales_order_no": so.order_no if so else None,
            "customer_id": so.customer_id if so else None,
            "customer_name": customer.name if customer else None,
            "model_id": po.model_id,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "cutting_factories": [
                _department_ref(department)
                for _, department in sorted(cutting_departments.items())
            ],
            "sewing_factories": [
                _department_ref(department)
                for _, department in sorted(sewing_factories.items())
            ],
            "sizes": [
                {
                    "size": quantities.get("size", size),
                    "planned_quantity": quantities["planned_quantity"],
                    "completed_quantity": quantities["completed_quantity"],
                    **({
                        "sewing_completed_quantity": int(
                            sewing_output.get("sizes", {}).get(size.casefold(), {}).get("completed_quantity", 0)
                        ),
                    } if sewing_completed_only else {}),
                }
                for size, quantities in size_totals.items()
            ],
            "model_image_url": model_display_image_url(model),
            "material_image_url": (
                fabric_batch.image_url if fabric_batch else None
            ) or material_preview_image_url(model),
            "cutting_passport_id": cutting_passports[0].id if cutting_passports else None,
            "cutting_passport_no": cutting_passports[0].passport_no if cutting_passports else None,
            "cutting_passports": [
                {
                    "id": passport.id,
                    "passport_no": passport.passport_no,
                    "lot_no": passport.lot_no,
                    "date": passport.date,
                }
                for passport in cutting_passports
            ],
            "current_stage": summary["current_stage"],
            "current_stage_status": summary["current_stage_status"],
            "current_sewing_flow": summary["current_sewing_flow"],
            "is_blocked": summary["is_blocked"],
            "blocked_by": summary["blocked_by"],
            "stages": stages,
            "batches": batches_out,
        })
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out


@router.get("/summary")
def summary(db: DbSession, _: CurrentUser):
    """Counts per status — useful for the top-row cards on the page."""
    rows = (
        db.query(ProductionOrder.status, func.count(ProductionOrder.id))
        .filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))
        .group_by(ProductionOrder.status)
        .all()
    )
    counts = {status: int(total) for status, total in rows}
    return {"counts": counts, "total_active": int(sum(counts.values()))}
