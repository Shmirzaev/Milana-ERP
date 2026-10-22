"""Keep bundle receipts and Sewing record input from crediting pieces twice."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Bundle, SewingRecord, WorkOrder


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
    if wo.production_batch_id is not None:
        received_query = received_query.filter(Bundle.production_batch_id == wo.production_batch_id)
    received = dict(received_query.group_by(Bundle.production_batch_id).all())
    # A shared work order can contain several Nastils. Receipt for Nastil 1
    # must not hide separately recorded input for Nastil 2.
    wo.actual_input_qty = sum(max(int(recorded.get(batch_id) or 0), int(received.get(batch_id) or 0))
        for batch_id in recorded.keys() | received.keys())
