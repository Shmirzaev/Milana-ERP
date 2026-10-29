"""Reconcile shared Sewing status when another Nastil changes its evidence.

Read helpers never repair data. Write callers flush their evidence and lock the
Sewing work orders before reconciling; existing records and quantities survive.
"""
from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError
from fastapi import HTTPException

from app.schemas import Bundle, CuttingRecord, PrintingRecord, ProductionBatch, SewingRecord, WorkOrder
from app.models.audit_service import log_action


def unfinished_sewing_batches(db, wo):
    """Actual work is batch-scoped; one Nastil's excess cannot cover another.

    A saved, positive plan without confirmed output is still pending. A batch
    already cut short uses its confirmed usable output, retaining the existing
    explicit-shortfall completion rule without treating shortages as garments.
    """
    batches = db.query(ProductionBatch.id, ProductionBatch.planned_quantity).filter(
        ProductionBatch.production_order_id == wo.production_order_id)
    cutting = db.query(CuttingRecord.production_batch_id, func.sum(CuttingRecord.passed_pieces)).join(
        WorkOrder, WorkOrder.id == CuttingRecord.work_order_id).filter(
        WorkOrder.production_order_id == wo.production_order_id,
        WorkOrder.status.notin_(("cancelled", "rejected")),
        CuttingRecord.approval_status == "approved",
        or_(CuttingRecord.material_role.is_(None), CuttingRecord.material_role == "main"))
    received = db.query(Bundle.production_batch_id, func.sum(Bundle.quantity)).filter(
        Bundle.production_order_id == wo.production_order_id, Bundle.status == "received_sewing")
    print_batch = func.coalesce(PrintingRecord.production_batch_id, WorkOrder.production_batch_id)
    printing = db.query(print_batch, func.sum(PrintingRecord.passed_qty), func.sum(PrintingRecord.rejected_qty)).join(
        WorkOrder, WorkOrder.id == PrintingRecord.work_order_id).filter(
        WorkOrder.production_order_id == wo.production_order_id,
        WorkOrder.operation == "printing", WorkOrder.status.notin_(("cancelled", "rejected", "skipped")))
    record_batch = func.coalesce(SewingRecord.production_batch_id, wo.production_batch_id)
    sewn = db.query(record_batch, func.sum(
        SewingRecord.passed_qty + SewingRecord.failed_qty + SewingRecord.rejected_qty)).filter(
        SewingRecord.work_order_id == wo.id)
    from app.models.production.batch_scope_service import filter_work_order_batches
    batches = filter_work_order_batches(batches, ProductionBatch.id, wo)
    cutting = filter_work_order_batches(cutting, CuttingRecord.production_batch_id, wo)
    received = filter_work_order_batches(received, Bundle.production_batch_id, wo)
    printing = filter_work_order_batches(printing, print_batch, wo)
    plans = dict(batches.all())
    cut = dict(cutting.group_by(CuttingRecord.production_batch_id).all())
    receipts = dict(received.group_by(Bundle.production_batch_id).all())
    printed = {bid: (int(passed or 0), int(rejected or 0))
               for bid, passed, rejected in printing.group_by(print_batch).all()}
    output = dict(sewn.group_by(record_batch).all())
    pending = {bid for bid, quantity in plans.items()
               if int(quantity or 0) > 0 and bid not in cut and bid not in receipts}
    for bid in cut.keys() | receipts.keys() | printed.keys():
        printed_passed, printed_loss = printed.get(bid, (0, 0))
        # Printing rejects are real losses in this exact Nastil. Bundle labels
        # may retain their original Cutting count; do not demand those rejects
        # again at Sewing or subtract them from another Nastil's allowance.
        target = max(0, int(cut.get(bid) or 0) - printed_loss,
                     int(receipts.get(bid) or 0) - printed_loss, printed_passed)
        # Historical unbatched entries have only aggregate counters. Preserve
        # that supported path; normal aggregate completion validates it.
        actual = int(output.get(bid) or 0)
        if bid is None and not plans:
            actual = max(actual, int(wo.passed_qty or 0) + int(wo.failed_qty or 0))
        if target > actual:
            pending.add(bid)
    return pending


def reconcile_sewing_order(db, production_order_id, *, current=None, reason="Sewing evidence changed"):
    """Reopen only completed work with unfinished evidence; never write on GET.

    All receipt routes use this after their final bundle, including receipts
    without a new assignment. Existing completed assignments remain completed.
    """
    db.flush()
    try:
        rows = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "sewing", WorkOrder.status == "completed",
        ).order_by(WorkOrder.id).with_for_update(of=WorkOrder, nowait=True).populate_existing().all()
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03":
            raise HTTPException(409, "Sewing is being updated. Reload this batch and try again.") from error
        raise
    for wo in rows:
        from app.models.workflow_service import _complete_if_done
        old = {"status": wo.status, "end_time": wo.end_time}
        _complete_if_done(db, wo)
        if wo.status != old["status"]:
            log_action(db, current, "reopen_later_nastil", "WorkOrder", wo.id,
                       old_value=old, new_value={"status": wo.status, "end_time": wo.end_time,
                                                "reason": reason})
