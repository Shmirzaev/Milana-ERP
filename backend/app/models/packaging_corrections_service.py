"""Release entered Packaging output when an unused production label is deleted."""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func

from app.schemas import Department, PackagingReceipt, PackagingRecord, StockMovement, WorkOrder
from app.models.audit_service import log_action


def _work_state(work):
    return {key: getattr(work, key) for key in (
        "id", "status", "actual_input_qty", "actual_output_qty", "passed_qty", "failed_qty",
        "start_time", "end_time",
    )}


def undo_package_output(db, package):
    if not package.production_order_id:
        return
    from app.models.packages_service import _existing_package_totals_by_batch

    allocations = defaultdict(int)
    for allocation in package.batch_allocations:
        allocations[allocation.production_batch_id] += allocation.quantity
    if not allocations:
        allocations[package.production_batch_id] = package.total_quantity
    if sum(allocations.values()) != package.total_quantity:
        raise HTTPException(409, "Package batch evidence does not match its quantity")

    work_orders = db.query(WorkOrder).join(Department).filter(
        WorkOrder.production_order_id == package.production_order_id,
        WorkOrder.operation == "packaging",
        Department.code == package.packaging_department_code,
    ).order_by(WorkOrder.id).with_for_update(of=WorkOrder).populate_existing().all()
    by_id = {work.id: work for work in work_orders}
    records = db.query(PackagingRecord).filter(
        PackagingRecord.work_order_id.in_(by_id),
    ).order_by(PackagingRecord.id).with_for_update().populate_existing().all()
    # First Grade may be entered directly from Sewing, without a Packaging record.
    # Deleting that label already releases its exact size balance.
    by_batch = defaultdict(list)
    for record in records:
        batch_id = record.production_batch_id or by_id[record.work_order_id].production_batch_id
        by_batch[batch_id].append(record)
    if package.stock_kind == "first_grade" and all(not by_batch[batch_id] for batch_id in allocations):
        return
    remaining_packages = _existing_package_totals_by_batch(
        db, package.production_order_id, exclude_package_id=package.id,
    )
    changes = []
    for batch_id, quantity in allocations.items():
        candidates = by_batch[batch_id]
        total = sum(record.packed_qty for record in candidates)
        if total < quantity + remaining_packages.get(batch_id, 0):
            raise HTTPException(409, "Packaging output cannot be reset without affecting other packages")
        # Newest output is corrected first; older records and defects stay intact.
        for record in reversed(candidates):
            take = min(quantity, record.packed_qty)
            if not take:
                continue
            if record.input_qty < record.packed_qty + record.damaged_qty:
                raise HTTPException(409, "Packaging record quantities require review before deletion")
            if record.package_count or record.total_packed_quantity:
                raise HTTPException(409, "Packaging record quantities require review before deletion")
            if by_id[record.work_order_id].service_packaging_json is not None:
                raise HTTPException(409, "Edit Usluga quantities through size confirmation")
            next_packed = record.packed_qty - take
            # When the last good piece is undone, release any unprocessed input
            # too. Damaged pieces and their material/waste evidence remain used.
            next_input = record.input_qty - take if next_packed else record.damaged_qty
            changes.append((record, next_input, next_packed))
            quantity -= take
            if not quantity:
                break
    changed_ids = [record.id for record, _, _ in changes]
    if changed_ids and db.query(StockMovement.id).filter(
        StockMovement.reference_type == "PackagingRecord",
        StockMovement.reference_id.in_(changed_ids),
    ).first():
        # Do not mint consumed materials or charge them twice on re-entry.
        raise HTTPException(409, "Packaging material usage must be corrected before deleting this package")

    before, after = [], []
    changed_work_ids = {record.work_order_id for record, _, _ in changes}
    work_before = [_work_state(by_id[work_id]) for work_id in sorted(changed_work_ids)]
    for record, next_input, next_packed in changes:
        before.append({"id": record.id, "work_order_id": record.work_order_id,
                       "production_batch_id": record.production_batch_id,
                       "input_qty": record.input_qty, "packed_qty": record.packed_qty,
                       "damaged_qty": record.damaged_qty})
        record.input_qty = next_input
        record.packed_qty = next_packed
        after.append({**before[-1], "input_qty": next_input, "packed_qty": next_packed})
    for work_id in changed_work_ids:
        work = by_id[work_id]
        own_records = [record for record in records if record.work_order_id == work_id]
        work.actual_output_qty = work.passed_qty = sum(record.packed_qty for record in own_records)
        # Receipt-led intake stays unchanged. Older workflows derive intake from
        # their entry ledger; recompute it so subsequent re-entry cannot double it.
        has_receipts = db.query(PackagingReceipt.id).filter_by(work_order_id=work_id).first()
        if not has_receipts:
            work.actual_input_qty = sum(record.input_qty for record in own_records)
        if work.status == "completed":
            work.status = "in_progress"
            work.end_time = None
    db.flush()
    return {"before": before, "after": after, "quantity": package.total_quantity,
            "work_before": work_before,
            "work_after": [_work_state(by_id[work_id]) for work_id in sorted(changed_work_ids)]}


def finish_package_output_reset(db, production_order_id, request, correction, *,
                                actor=None, package_id=None, package_no=None):
    if not correction:
        return
    # Persist recalculated storage counters before refreshing locked work orders.
    db.flush()
    from app.schemas import Package, User
    from app.models.workflow_service import sync_production_order_status

    received = db.query(func.count(Package.id)).filter(
        Package.production_order_id == production_order_id,
        Package.status.in_(["received_in_storage", "reserved", "shipped", "delivered"]),
    ).scalar()
    if not received or request is None:
        for work in db.query(WorkOrder).filter_by(
            production_order_id=production_order_id, operation="storage_transfer",
        ).order_by(WorkOrder.id).with_for_update().populate_existing():
            if work.status not in {"cancelled", "rejected"} and not any([
                work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty, work.rework_qty,
            ]):
                correction["work_before"].append(_work_state(work))
                work.status = "waiting"
                work.start_time = work.end_time = None
                correction["work_after"].append(_work_state(work))
            elif request is None and work.status == "completed" and work.passed_qty < work.planned_output_qty:
                correction["work_before"].append(_work_state(work))
                work.status = "in_progress" if work.passed_qty else "waiting"
                work.end_time = None
                correction["work_after"].append(_work_state(work))
    db.flush()
    sync_production_order_status(db, production_order_id)
    if request is not None:
        actor_id = request.reviewed_by or request.requested_by
        actor = db.get(User, actor_id) if actor_id else None
        package_no = request.package_no
    log_action(db, actor, "undo_package_output", "PackageChangeRequest" if request else "Package",
               request.id if request else package_id,
               old_value={"records": correction["before"], "work_orders": correction["work_before"]},
               new_value={"package_no": package_no, "quantity": correction["quantity"],
                          "records": correction["after"], "work_orders": correction["work_after"],
                          "sewing_receipts_preserved": True})
