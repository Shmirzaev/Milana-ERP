"""First Grade is good output sold by size, never defects or extra stock."""
from collections import defaultdict
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlalchemy import func

from app.schemas import Package, SewingRecord, WorkOrder, ProductionOrderItem, ProductionOrder, ProductionBatch


def _size_evidence(db, production_order_id, batch_id, *, exclude_package_id=None):
    order = db.get(ProductionOrder, production_order_id)
    if batch_id is not None:
        batch = db.get(ProductionBatch, batch_id)
        if not batch or batch.production_order_id != production_order_id:
            raise HTTPException(404, "Production batch not found")
    elif db.query(ProductionBatch.id).filter_by(production_order_id=production_order_id).first():
        raise HTTPException(409, "FIRST_GRADE_BATCH_REQUIRED")
    records = db.query(SewingRecord).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id == production_order_id,
        func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id) == batch_id,
    ).order_by(SewingRecord.id).all()
    source = [[r.id, r.passed_qty, r.size_quantities, r.correction_version] for r in records]
    source_version = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    saved = (order.packaging_size_breakdowns or {}).get(str(batch_id))
    accepted = defaultdict(int)
    complete = bool(records)
    for record in records:
        rows = record.size_quantities or []
        if sum(int(row.get("quantity", 0)) for row in rows) != record.passed_qty:
            complete = False
        for row in rows:
            accepted[str(row["size"])] += int(row["quantity"])
    if saved:
        complete = saved["source_version"] == source_version
        accepted = defaultdict(int, {row["size"]: row["quantity"] for row in saved["sizes"]})
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
    total = sum(record.passed_qty for record in records)
    complete = complete and total > 0 and sum(accepted.values()) == total
    complete = complete and not any(qty > accepted.get(size, 0) for size, qty in consumed.items())
    sizes = {row.size for row in db.query(ProductionOrderItem).filter_by(production_order_id=production_order_id)}
    sizes.update(accepted)
    sizes.update(consumed)
    version = hashlib.sha256(json.dumps([source_version, saved, sorted(consumed.items())], sort_keys=True).encode()).hexdigest()
    return {"needs_size_entry": not complete, "total": total, "version": version,
            "source_version": source_version,
            "sizes": [{"size": size, "accepted": accepted[size] if complete else None,
                       "packed": consumed[size], "remaining": max(0, accepted[size] - consumed[size]) if complete else 0}
                      for size in sorted(sizes)]}


def packaging_size_entry(db, production_order_id, batch_id):
    state = _size_evidence(db, production_order_id, batch_id)
    return {key: value for key, value in state.items() if key != "source_version"}


def save_packaging_size_entry(db, order, batch_id, payload, current):
    from app.models.audit_service import log_action
    state = _size_evidence(db, order.id, batch_id)
    if state["version"] != payload.version or not state["needs_size_entry"]:
        raise HTTPException(409, "FIRST_GRADE_SIZE_STALE")
    allowed = {row["size"]: row for row in state["sizes"]}
    submitted = {}
    for row in payload.sizes:
        size = row.size.strip()
        if size not in allowed or size in submitted:
            raise HTTPException(422, "FIRST_GRADE_SIZE_INVALID")
        submitted[size] = row.quantity
    if state["total"] <= 0 or sum(submitted.values()) != state["total"]:
        raise HTTPException(409, "FIRST_GRADE_SIZE_TOTAL")
    if any(submitted.get(size, 0) < row["packed"] for size, row in allowed.items()):
        raise HTTPException(409, "FIRST_GRADE_SIZE_PACKED")
    old = (order.packaging_size_breakdowns or {}).get(str(batch_id))
    saved = {"source_version": state["source_version"],
             "sizes": [{"size": size, "quantity": qty} for size, qty in sorted(submitted.items())]}
    if old != saved:
        order.packaging_size_breakdowns = {**(order.packaging_size_breakdowns or {}), str(batch_id): saved}
        log_action(db, current, "update", "ProductionOrder", order.id,
                   old_value={"production_batch_id": batch_id, "packaging_size_breakdown": old},
                   new_value={"production_batch_id": batch_id, "packaging_size_breakdown": saved})
        db.flush()
    return packaging_size_entry(db, order.id, batch_id)


def size_balance(db, production_order_id, batch_id, *, exclude_package_id=None):
    state = _size_evidence(db, production_order_id, batch_id, exclude_package_id=exclude_package_id)
    if state["needs_size_entry"]:
        raise HTTPException(409, "FIRST_GRADE_SIZE_EVIDENCE_REQUIRED")
    return state["sizes"]


def enforce_size_allocation(db, order, batch_id, items, allocations, *, first_grade=False, exclude_package_id=None, cache=None):
    cache = cache if exclude_package_id is None else None
    singles_key = ("has_singles", order.id)
    has_singles = first_grade or (cache.get(singles_key) if cache is not None else None)
    if has_singles is None or (not has_singles and first_grade):
        has_singles = bool(db.query(Package.id).filter(
            Package.production_order_id == order.id, Package.stock_kind.in_(["first_grade", "second_grade"]),
        ).first())
    if cache is not None:
        cache[singles_key] = has_singles
    if not has_singles:
        return
    colors_key = ("colors", order.id)
    colors = cache.get(colors_key) if cache is not None else None
    if colors is None:
        sources = db.query(ProductionOrderItem).filter_by(production_order_id=order.id).all()
        colors = {str(row.color or "").strip().casefold() for row in sources}
        if cache is not None:
            cache[colors_key] = colors
    if len(colors) != 1 or any(item.get("model_id", order.model_id) != order.model_id or str(item["color"]).strip().casefold() not in colors for item in items):
        raise HTTPException(409, "FIRST_GRADE_VARIANT_EVIDENCE")
    if len(allocations) > 1:
        raise HTTPException(409, "FIRST_GRADE_MIXED_BATCH_EVIDENCE")
    selected_batch = allocations[0]["production_batch_id"] if allocations else batch_id
    balance_key = ("balance", order.id, selected_batch)
    balance = cache.get(balance_key) if cache is not None else None
    if balance is None:
        balance = {row["size"]: row["remaining"] for row in size_balance(
            db, order.id, selected_batch, exclude_package_id=exclude_package_id,
        )}
        if cache is not None:
            cache[balance_key] = balance
    requested = defaultdict(int)
    for item in items:
        requested[item["size"]] += item["quantity"]
    if any(qty > balance.get(size, 0) for size, qty in requested.items()):
        raise HTTPException(409, "FIRST_GRADE_SIZE_EXCEEDED")

    if cache is not None:
        for size, quantity in requested.items():
            balance[size] -= quantity
