"""Allocation evidence participates in the caller's locked outer transaction."""
from sqlalchemy.orm import Session

from app.schemas import PackageBatchAllocation


def insert_allocations(db: Session, package_id: int, allocations: list[dict]) -> None:
    for allocation in allocations:
        db.add(PackageBatchAllocation(package_id=package_id,
            production_batch_id=allocation["production_batch_id"], quantity=allocation["quantity"],
            item_breakdown=allocation.get("item_breakdown")))


def replace_allocations(db: Session, package_id: int, allocations: list[dict]) -> None:
    db.query(PackageBatchAllocation).filter_by(package_id=package_id).delete(synchronize_session=False)
    db.flush()
    insert_allocations(db, package_id, allocations)
