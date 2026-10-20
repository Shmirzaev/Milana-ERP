"""Authoritative batch freeze once Sewing has saved output."""

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError

from app.models import SewingAssignment, SewingDailyReport, SewingRecord, WorkOrder


LOCKED_MESSAGE = "This cutting batch cannot be edited or deleted after Sewing output has been recorded"


def sewing_output_batch_ids(db, production_order_id):
    """None denotes legacy output that cannot safely be attributed to one batch."""
    from sqlalchemy import select, union_all
    work_ids = select(WorkOrder.id).where(
        WorkOrder.production_order_id == production_order_id, WorkOrder.operation == "sewing",
    )
    rows = db.execute(union_all(
        select(SewingRecord.production_batch_id).where(SewingRecord.work_order_id.in_(work_ids)),
        select(SewingDailyReport.production_batch_id).where(
            SewingDailyReport.production_order_id == production_order_id, SewingDailyReport.sewn_qty > 0,
        ),
        select(SewingAssignment.production_batch_id).where(
            SewingAssignment.work_order_id.in_(work_ids), SewingAssignment.completed_qty > 0,
        ),
        select(WorkOrder.production_batch_id).where(
            WorkOrder.id.in_(work_ids),
            or_(WorkOrder.actual_output_qty > 0, WorkOrder.passed_qty > 0, WorkOrder.failed_qty > 0),
            ~select(SewingRecord.id).where(SewingRecord.work_order_id == WorkOrder.id).exists(),
        ),
    ))
    return {row[0] for row in rows}


def require_cutting_batch_mutable(db, work_order, batch_id):
    # Sewing submissions hold this same row lock through output persistence.
    # Re-read evidence after acquiring it, never trust a cached UI flag.
    try:
        db.query(WorkOrder).filter(
            WorkOrder.production_order_id == work_order.production_order_id,
            WorkOrder.operation == "sewing",
        ).order_by(WorkOrder.id).with_for_update(of=WorkOrder, nowait=True).populate_existing().all()
    except OperationalError as error:
        # Some legacy writers acquire the order before the stage row, others
        # stage before order. Never wait while retaining the opposite lock.
        if getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03":
            raise HTTPException(409, "Sewing is being updated. Reload this batch and try again.") from error
        raise
    locked = sewing_output_batch_ids(db, work_order.production_order_id)
    if None in locked or batch_id in locked or (batch_id is None and locked):
        raise HTTPException(409, LOCKED_MESSAGE)
