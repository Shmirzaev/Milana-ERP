"""First Grade is good output sold by size, never defects or extra stock."""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import selectinload

from app.models import Package, SewingRecord, WorkOrder, ProductionOrderItem


def size_balance(db, production_order_id, batch_id, *, exclude_package_id=None):
    records = db.query(SewingRecord).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id == production_order_id,
        SewingRecord.production_batch_id == batch_id,
    ).all()
    accepted = defaultdict(int)
    for record in records:
        rows = record.size_quantities or []
        if sum(int(row.get("quantity", 0)) for row in rows) != record.passed_qty:
            raise HTTPException(409, "FIRST_GRADE_SIZE_EVIDENCE_REQUIRED")
        for row in rows:
            accepted[str(row["size"])] += int(row["quantity"])
    if not accepted:
        raise HTTPException(409, "FIRST_GRADE_SIZE_EVIDENCE_REQUIRED")
    consumed = defaultdict(int)
    packages = db.query(Package).options(selectinload(Package.items), selectinload(Package.batch_allocations)).filter(
        Package.production_order_id == production_order_id,
        Package.id != exclude_package_id if exclude_package_id else True,
    ).all()
    for package in packages:
        allocations = package.batch_allocations
        batch_ids = {a.production_batch_id for a in allocations}
        if len(batch_ids) > 1 and batch_id in batch_ids:
            # Historical multi-batch bags have no per-size/per-batch evidence.
            raise HTTPException(409, "FIRST_GRADE_MIXED_BATCH_EVIDENCE")
        if package.production_batch_id != batch_id and batch_id not in batch_ids:
            continue
        for item in package.items:
            consumed[item.size] += item.quantity
        if package.quantity_shortfall:
            # A warehouse correction cannot release an unknown size into production.
            raise HTTPException(409, "FIRST_GRADE_SIZE_EVIDENCE_REQUIRED")
    if any(qty > accepted.get(size, 0) for size, qty in consumed.items()):
        raise HTTPException(409, "FIRST_GRADE_SIZE_EVIDENCE_REQUIRED")
    return [{"size": size, "accepted": qty, "packed": consumed[size], "remaining": max(0, qty - consumed[size])}
            for size, qty in sorted(accepted.items())]


def enforce_size_allocation(db, order, batch_id, items, allocations, *, first_grade=False, exclude_package_id=None):
    has_singles = first_grade or db.query(Package.id).filter(
        Package.production_order_id == order.id, Package.stock_kind == "first_grade",
    ).first()
    if not has_singles:
        return
    sources = db.query(ProductionOrderItem).filter_by(production_order_id=order.id).all()
    colors = {str(row.color or "").strip().casefold() for row in sources}
    if len(colors) != 1 or any(item.get("model_id", order.model_id) != order.model_id or str(item["color"]).strip().casefold() not in colors for item in items):
        raise HTTPException(409, "FIRST_GRADE_VARIANT_EVIDENCE")
    if len(allocations) > 1:
        raise HTTPException(409, "FIRST_GRADE_MIXED_BATCH_EVIDENCE")
    selected_batch = allocations[0]["production_batch_id"] if allocations else batch_id
    balance = {row["size"]: row["remaining"] for row in size_balance(
        db, order.id, selected_batch, exclude_package_id=exclude_package_id,
    )}
    requested = defaultdict(int)
    for item in items:
        requested[item["size"]] += item["quantity"]
    if any(qty > balance.get(size, 0) for size, qty in requested.items()):
        raise HTTPException(409, "FIRST_GRADE_SIZE_EXCEEDED")
