"""Validate operator recipes without treating the plan as actual size output."""
from collections import Counter, defaultdict
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from app.libs.dto.packaging.tracking import PackageIn
from app.libs.enums.production import WorkOrderStatus
from app.schemas import Package, ProductionOrder, ProductionOrderItem, SewingRecord, WorkOrder


def validate_direct_identities(db: Session, order: ProductionOrder, packages: list[PackageIn]) -> None:
    variants = db.query(ProductionOrderItem).filter_by(production_order_id=order.id).all()
    allowed = {(str(row.color or "").strip().casefold(), str(row.size or "").strip()) for row in variants}
    if not allowed:
        raise HTTPException(409, "Order color and size evidence is required for direct packaging")
    for package in packages:
        color = package.color.strip().casefold()
        if any((item.color.strip().casefold(), item.size.strip()) not in allowed
               or item.color.strip().casefold() != color for item in package.items):
            raise HTTPException(409, "Package color and size must match the production order")
    # Graded output additionally uses its existing strict size/allocation checks
    # in create_package. Ordinary goods retain manual recipes if actual size
    # evidence is absent; the planned size proportions are never actual output.
    records = db.query(SewingRecord, WorkOrder.production_batch_id).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id == order.id, WorkOrder.operation == "sewing",
        WorkOrder.status != WorkOrderStatus.CANCELLED).order_by(SewingRecord.id).all()
    grouped = defaultdict(list)
    for record, work_batch in records:
        batch = record.production_batch_id if record.production_batch_id is not None else work_batch
        grouped[batch].append(record)
    actual = {}
    for batch, rows in grouped.items():
        source = [[row.id, row.passed_qty, row.size_quantities, row.correction_version] for row in rows]
        version = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        accepted = Counter()
        complete = all(sum(int(size.get("quantity", 0)) for size in row.size_quantities or []) == row.passed_qty for row in rows)
        for row in rows:
            for size in row.size_quantities or []:
                accepted[str(size["size"])] += int(size["quantity"])
        saved = (order.packaging_size_breakdowns or {}).get(str(batch))
        if saved and saved.get("source_version") == version:
            accepted = Counter({row["size"]: row["quantity"] for row in saved["sizes"]})
            complete = True
        total = sum(row.passed_qty for row in rows)
        if complete and total > 0 and sum(accepted.values()) == total:
            actual[batch] = accepted
    existing = db.query(Package).options(selectinload(Package.items), selectinload(Package.batch_allocations)).filter_by(
        production_order_id=order.id).all()
    consumed = defaultdict(Counter)
    ambiguous = set()
    global_consumed = Counter()
    for package in existing:
        quantities = Counter()
        for item in package.items:
            quantities[item.size] += item.quantity
        global_consumed.update(quantities)
        sources = {row.production_batch_id for row in package.batch_allocations} or {package.production_batch_id}
        if len(sources) == 1 and not package.quantity_shortfall:
            consumed[next(iter(sources))].update(quantities)
        else:
            ambiguous.update(sources)
    requested = Counter()
    single_requested = defaultdict(Counter)
    selected = set()
    for package in packages:
        sources = {row.production_batch_id for row in package.batch_allocations} or {package.production_batch_id}
        selected.update(sources)
        quantities = Counter()
        for item in package.items:
            quantities[item.size] += item.quantity
        requested.update(quantities)
        if len(sources) == 1:
            single_requested[next(iter(sources))].update(quantities)
    for batch, quantities in single_requested.items():
        if batch in actual and batch not in ambiguous:
            if any(quantity + consumed[batch][size] > actual[batch][size] for size, quantity in quantities.items()):
                raise HTTPException(409, "Package size quantity exceeds actual passed Sewing for this batch")
    if selected.issubset(actual) and not selected.intersection(ambiguous):
        available = Counter()
        for batch in selected:
            available.update(actual[batch])
            available.subtract(consumed[batch])
        if any(quantity > available[size] for size, quantity in requested.items()):
            raise HTTPException(409, "Package size quantity exceeds actual passed Sewing for selected sources")
    # Scalar mixed-batch allocations cannot establish a size x batch breakdown.
    # Still enforce order-wide actual size conservation when all source evidence
    # is complete, including existing mixed-source labels.
    if grouped and set(grouped).issubset(actual):
        accepted = Counter()
        for quantities in actual.values():
            accepted.update(quantities)
        if any(quantity + global_consumed[size] > accepted[size] for size, quantity in requested.items()):
            raise HTTPException(409, "Package size quantity exceeds actual passed Sewing for this order")
