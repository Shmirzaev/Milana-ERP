"""Exclusive Nastil ownership when a stage has shared and dedicated work orders."""
from sqlalchemy import select

from app.schemas import WorkOrder


def dedicated_batch_ids(order_id: int, operation: str):
    return select(WorkOrder.production_batch_id).where(
        WorkOrder.production_order_id == order_id, WorkOrder.operation == operation,
        WorkOrder.production_batch_id.is_not(None), WorkOrder.status != "cancelled")


def batch_owned_by_work_order(db, work, batch_id: int) -> bool:
    if work.production_batch_id is not None:
        return work.production_batch_id == batch_id
    return batch_id not in set(db.scalars(dedicated_batch_ids(work.production_order_id, work.operation)))


def filter_work_order_batches(query, column, work):
    if work.production_batch_id is not None:
        return query.filter(column == work.production_batch_id)
    from sqlalchemy import or_
    return query.filter(or_(column.is_(None), column.notin_(dedicated_batch_ids(work.production_order_id, work.operation))))
