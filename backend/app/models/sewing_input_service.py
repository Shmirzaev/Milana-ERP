"""Keep bundle receipts and Sewing record input from crediting pieces twice."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.schemas import Bundle, PrintingRecord, SewingRecord, WorkOrder


def usable_sewing_input_quantity(
    *, cutting_qty: int = 0, received_qty: int = 0,
    printing_passed_qty: int = 0, printing_rejected_qty: int = 0,
) -> int:
    """Confirmed Sewing work excludes exact-Nastil Printing losses.

    Cutting bundle labels can retain their original count. This is the existing
    completion target arithmetic, shared with receipt assignment so the line does
    not owe pieces that were rejected upstream.
    """
    return max(0, cutting_qty - printing_rejected_qty,
               received_qty - printing_rejected_qty, printing_passed_qty)


def sewing_receipt_printing_totals(production_order_id: int, production_batch_id: int) -> Subquery:
    """One bounded aggregate, executed after the caller's bundle-lock waits.

    Constructing this statement performs no query. A fresh statement snapshot
    sees Printing evidence committed while a legacy receipt waited for bundles.
    The scan is independent of how many bundles are received.
    """
    print_batch = func.coalesce(PrintingRecord.production_batch_id, WorkOrder.production_batch_id)
    return select(
        func.coalesce(func.sum(PrintingRecord.passed_qty), 0).label("printing_passed_qty"),
        func.coalesce(func.sum(PrintingRecord.rejected_qty), 0).label("printing_rejected_qty"),
    ).select_from(PrintingRecord).join(WorkOrder, WorkOrder.id == PrintingRecord.work_order_id).where(
        WorkOrder.production_order_id == production_order_id,
        WorkOrder.operation == "printing",
        WorkOrder.status.notin_(("cancelled", "rejected", "skipped")),
        print_batch == production_batch_id,
    ).subquery()


def usable_sewing_receipt_quantity(
    *, received_qty: int, printing_passed_qty: int, printing_rejected_qty: int,
) -> int:
    # An upstream record must never manufacture more line work than this exact
    # batch's physical receipt. No bundle labels/quantities are rewritten.
    return min(received_qty, usable_sewing_input_quantity(
        received_qty=received_qty, printing_passed_qty=printing_passed_qty,
        printing_rejected_qty=printing_rejected_qty,
    ))


def sync_sewing_input(db: Session, wo: WorkOrder) -> None:
    """Rebuild the display counter under the caller's WorkOrder write lock.

    Bundle receipts and record input are overlapping evidence, not additive
    deliveries. Record validation uses its own ledger total, while the work
    order must still show every piece physically received after corrections.
    Call after flushing any record creation, correction or deletion.
    """
    recorded = dict(db.query(SewingRecord.production_batch_id, func.sum(SewingRecord.input_qty)).filter(
        SewingRecord.work_order_id == wo.id,
    ).group_by(SewingRecord.production_batch_id).all())
    received_query = db.query(Bundle.production_batch_id, func.sum(Bundle.quantity)).filter(
        Bundle.production_order_id == wo.production_order_id,
        Bundle.status == "received_sewing",
    )
    from app.models.production.batch_scope_service import filter_work_order_batches
    received_query = filter_work_order_batches(received_query, Bundle.production_batch_id, wo)
    received = dict(received_query.group_by(Bundle.production_batch_id).all())
    # A shared work order can contain several Nastils. Receipt for Nastil 1
    # must not hide separately recorded input for Nastil 2.
    wo.actual_input_qty = sum(max(int(recorded.get(batch_id) or 0), int(received.get(batch_id) or 0))
        for batch_id in recorded.keys() | received.keys())
