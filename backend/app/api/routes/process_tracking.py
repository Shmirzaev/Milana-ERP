"""Cross-department process tracking.

Returns, for every active production order, the current stage of each linked
work order — which department is working on it, how many units are done vs
planned, deadlines, sewing-flow assignment, overdue and block flags.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, is_admin, user_permissions
from app.models import (
    SalesOrder, ProductionOrder, Customer, Model, SewingFlow, SewingAssignment, User,
    CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord, Package, PackageBatchAllocation,
)
from app.core.dt import as_utc

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


def _can_view(user: User) -> bool:
    if is_admin(user):
        return True
    if user.role and user.role.name in ("Admin", "Management", "Sales", "Planning"):
        return True
    perms = user_permissions(user)
    return any(p in perms for p in ("processes.view", "sales.orders", "planning.production"))


def _stage_dict(wo, flow, now: datetime) -> dict:
    deadline_dt = as_utc(wo.deadline)
    overdue = bool(deadline_dt and wo.status not in _TERMINAL_STATUSES and deadline_dt < now)
    planned = int(wo.planned_output_qty or 0)
    done = int(wo.passed_qty or 0)
    pct = round(100.0 * done / planned, 1) if planned > 0 else 0.0
    return {
        "work_order_id": wo.id,
        "operation": wo.operation,
        "department_id": wo.department_id,
        "status": wo.status,
        "planned": planned,
        "completed": done,
        "failed": int(wo.failed_qty or 0),
        "rework": int(wo.rework_qty or 0),
        "progress_pct": pct,
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
    rework = sum(int(r["rework"] or 0) for r in rows)
    pct = round(100.0 * completed / planned, 1) if planned > 0 else 0.0

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
        "rework": rework,
        "progress_pct": pct,
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
            row["rework"] = int(total.get("rework", 0))
            row["progress_pct"] = round(100.0 * completed / planned, 1) if planned > 0 else 0.0
            row["status"] = _batch_stage_status(str(base.get("status") or "waiting"), planned, completed, activity)
            rows.append(row)
        out[int(b.id)] = rows
    return out


def _process_summary(stages: list[dict], po_status: str) -> dict:
    blocked = next((s for s in stages if s.get("is_blocked")), None)
    current_stage = next((s for s in stages if str(s.get("status")) not in _TERMINAL_STATUSES), None)
    if not stages:
        current_stage_label = "planning_required"
        current_stage_status = po_status
    elif current_stage is None:
        current_stage_label = "completed"
        current_stage_status = None
    else:
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
    only_active: bool = True,
):
    """One row per Production Order with rolled-up stage progress.

    Uses bulk lookups for Model / SalesOrder / Customer / SewingFlow to avoid
    N+1 queries when there are many production orders.
    """
    if not _can_view(current):
        raise HTTPException(403, "Not allowed to view process tracking")

    qry = db.query(ProductionOrder).options(
        selectinload(ProductionOrder.batches),
        selectinload(ProductionOrder.work_orders),
        selectinload(ProductionOrder.items),
    )
    if status:
        qry = qry.filter(ProductionOrder.status == status)
    if only_active:
        qry = qry.filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))

    pos = qry.order_by(ProductionOrder.id.desc()).all()

    # Bulk-load related entities so we resolve names without N+1 queries.
    model_ids = {p.model_id for p in pos if p.model_id}
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

    models = {m.id: m for m in (db.query(Model).filter(Model.id.in_(model_ids)).all() if model_ids else [])}
    sos = {s.id: s for s in (db.query(SalesOrder).filter(SalesOrder.id.in_(so_ids)).all() if so_ids else [])}
    customer_ids = {s.customer_id for s in sos.values() if s.customer_id}
    customers = {c.id: c for c in (db.query(Customer).filter(Customer.id.in_(customer_ids)).all() if customer_ids else [])}
    flows = {f.id: f for f in (db.query(SewingFlow).filter(SewingFlow.id.in_(flow_ids)).all() if flow_ids else [])}

    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for po in pos:
        model = models.get(po.model_id)
        so = sos.get(po.sales_order_id) if po.sales_order_id else None
        customer = customers.get(so.customer_id) if so and so.customer_id else None

        by_batch: dict[int | None, list[dict]] = {}
        all_stage_rows: list[dict] = []
        for wo in po.work_orders:
            flow = flows.get(wo.sewing_flow_id) if wo.sewing_flow_id else None
            stage = _stage_dict(wo, flow, now)
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

        by_op: dict[str, list[dict]] = {}
        for s in all_stage_rows:
            by_op.setdefault(str(s["operation"]), []).append(s)
        stages: list[dict] = []
        for op in _OP_ORDER:
            rows = by_op.get(op, [])
            if rows:
                stages.append(_rollup_operation(op, rows))
        summary = _process_summary(stages, po.status)
        internal_batch_mode = bool(po.batches) and all(w.production_batch_id is None for w in po.work_orders)
        internal_batch_stages = _internal_batch_stage_rows(db, po, stages) if internal_batch_mode else {}

        batches_out: list[dict] = []
        for b in sorted(po.batches, key=lambda x: (int(x.batch_index or 0), int(x.id or 0))):
            batch_stages = internal_batch_stages.get(int(b.id), []) if internal_batch_mode else by_batch.get(b.id, [])
            batch_summary = _process_summary(batch_stages, po.status)
            batches_out.append({
                "id": b.id,
                "batch_no": b.batch_no,
                "batch_index": b.batch_index,
                "name": b.name,
                "planned_quantity": b.planned_quantity,
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

        out.append({
            "production_order_id": po.id,
            "production_no": po.production_no,
            "order_no": po.order_no,
            "production_type": po.production_type,
            "po_status": po.status,
            "po_deadline": po.deadline,
            "po_overdue": po_overdue,
            "planned_quantity": po.planned_quantity,
            "sales_order_id": po.sales_order_id,
            "sales_order_no": so.order_no if so else None,
            "customer_id": so.customer_id if so else None,
            "customer_name": customer.name if customer else None,
            "model_id": po.model_id,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "current_stage": summary["current_stage"],
            "current_stage_status": summary["current_stage_status"],
            "current_sewing_flow": summary["current_sewing_flow"],
            "is_blocked": summary["is_blocked"],
            "blocked_by": summary["blocked_by"],
            "stages": stages,
            "batches": batches_out,
        })
    return out


@router.get("/summary")
def summary(db: DbSession, current: CurrentUser):
    """Counts per status — useful for the top-row cards on the page."""
    if not _can_view(current):
        raise HTTPException(403, "Not allowed")
    rows = (
        db.query(ProductionOrder.status, func.count(ProductionOrder.id))
        .filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))
        .group_by(ProductionOrder.status)
        .all()
    )
    counts = {status: int(total) for status, total in rows}
    return {"counts": counts, "total_active": int(sum(counts.values()))}
