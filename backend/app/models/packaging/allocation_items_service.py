"""Conserve operator-confirmed source contents without inventing legacy evidence."""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import hashlib
import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import exists, inspect
from sqlalchemy.orm.attributes import NO_VALUE
from sqlalchemy.orm import Session, selectinload

from app.libs.dto.packaging.package_allocation_items import PackageAllocationItem
from app.libs.enums.production import WorkOrderStatus
from app.schemas import Package, PackageBatchAllocation, ProductionBatch, ProductionOrder, SewingRecord, WorkOrder
from app.schemas.fulfillment.shipment_review import PackageQuantityAdjustment


def normalized_items(items: list[dict]) -> list[dict]:
    quantities = Counter()
    try:
        for item in items:
            row = PackageAllocationItem.model_validate(item)
            quantities[(row.model_id, row.color.casefold(), row.size)] += row.quantity
    except ValidationError as error:
        raise HTTPException(422, "Invalid source item breakdown") from error
    return [{"model_id": model, "color": color, "size": size, "quantity": quantity}
            for (model, color, size), quantity in sorted(quantities.items())]


def item_totals(items: list[dict]) -> Counter:
    return Counter({(row["model_id"], row["color"], row["size"]): row["quantity"]
                    for row in normalized_items(items)})


def allocation_payload(row) -> dict:
    return {"production_batch_id": int(row.production_batch_id), "quantity": int(row.quantity),
            "item_breakdown": row.item_breakdown}


def allocation_read_payloads(db: Session, package_ids: list[int], *, packages: list[Package] | None = None) -> dict[int, list[dict]]:
    result = {package_id: [] for package_id in package_ids}
    pending = package_ids
    if packages is not None:
        pending = []
        loaded = []
        for package in packages:
            if package.production_order_id is None:
                continue
            allocations = inspect(package).attrs.batch_allocations.loaded_value
            if allocations is NO_VALUE:
                pending.append(package.id)
            else:
                loaded.extend(allocations)
        batch_ids = sorted({row.production_batch_id for row in loaded})
        batches = {}
        for offset in range(0, len(batch_ids), 400):
            batches.update({row.id: row for row in db.query(ProductionBatch).filter(
                ProductionBatch.id.in_(batch_ids[offset:offset + 400])).all()})
        for row in loaded:
            batch = batches.get(row.production_batch_id)
            result[row.package_id].append({**allocation_payload(row), "batch_no": batch.batch_no if batch else None,
                                           "batch_name": batch.name if batch else None})
    for offset in range(0, len(pending), 400):
        rows = db.query(PackageBatchAllocation, ProductionBatch.batch_no, ProductionBatch.name).join(
            ProductionBatch, ProductionBatch.id == PackageBatchAllocation.production_batch_id).filter(
            PackageBatchAllocation.package_id.in_(pending[offset:offset + 400])).order_by(PackageBatchAllocation.id).all()
        for allocation, number, name in rows:
            result[allocation.package_id].append({**allocation_payload(allocation), "batch_no": number, "batch_name": name})
    return result


def normalize_matrix(allocations: list[dict], items: list[dict], *,
                     raw_allocations: list[dict] | None = None,
                     preserve_unknown: bool = False, allow_unattributed: bool = False) -> list[dict]:
    """Keep exact evidence when supplied and preserve uncertainty for direct mixed packages."""
    if not allocations:
        return []
    raw_by_batch = {}
    for row in raw_allocations if raw_allocations is not None else allocations:
        batch = int(row["production_batch_id"])
        if batch in raw_by_batch:
            previous = raw_by_batch[batch].get("item_breakdown")
            additional = row.get("item_breakdown")
            if (previous is None) != (additional is None):
                raise HTTPException(400, "Every repeated source row requires its item breakdown")
            raw_by_batch[batch] = {**row, "item_breakdown": previous + additional if previous is not None else None}
        else:
            raw_by_batch[batch] = row
    result, combined = [], Counter()
    unique_items = normalized_items(items) if allow_unattributed else []
    for allocation in allocations:
        batch = int(allocation["production_batch_id"])
        raw = raw_by_batch.get(batch, {})
        breakdown = raw.get("item_breakdown")
        if len(allocations) == 1 and not preserve_unknown:
            inferred = normalized_items(items)
            if breakdown is not None and item_totals(breakdown) != item_totals(inferred):
                raise HTTPException(400, "Source item breakdown must match package contents")
            breakdown = inferred
        elif breakdown is None and len(unique_items) == 1:
            breakdown = [{**unique_items[0], "quantity": allocation["quantity"]}]
        elif breakdown is None:
            if not (preserve_unknown or allow_unattributed):
                raise HTTPException(409, "MIXED_PACKAGE_ITEM_BREAKDOWN_REQUIRED")
            result.append({**allocation, "item_breakdown": None})
            continue
        breakdown = normalized_items(breakdown)
        if not breakdown or sum(row["quantity"] for row in breakdown) != allocation["quantity"]:
            raise HTTPException(400, "Source item breakdown must equal its batch quantity")
        combined.update(item_totals(breakdown))
        result.append({**allocation, "item_breakdown": breakdown})
    if any(row["item_breakdown"] is None for row in result):
        if any(row["item_breakdown"] is not None for row in result):
            raise HTTPException(409, "MIXED_PACKAGE_ITEM_BREAKDOWN_REQUIRED")
    elif combined != item_totals(items):
        raise HTTPException(400, "Source item breakdowns must conserve every package model, color and size")
    return result


@dataclass
class SourceSizeState:
    actual: dict[int | None, Counter]
    consumed: dict[int | None, Counter]
    unknown: dict[int | None, Counter]


def source_size_state(db: Session, order: ProductionOrder, *, exclude_package_id: int | None = None) -> SourceSizeState:
    records = db.query(SewingRecord, WorkOrder.production_batch_id).join(
        WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id == order.id, WorkOrder.operation == "sewing",
        WorkOrder.status != WorkOrderStatus.CANCELLED).order_by(SewingRecord.id).all()
    grouped = defaultdict(list)
    for row, work_batch in records:
        grouped[row.production_batch_id if row.production_batch_id is not None else work_batch].append(row)
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
    packages = db.query(Package, exists().where(PackageQuantityAdjustment.package_id == Package.id)).options(
        selectinload(Package.items), selectinload(Package.batch_allocations)).filter(
        Package.production_order_id == order.id,
        Package.id != exclude_package_id if exclude_package_id is not None else True).all()
    consumed, unknown = defaultdict(Counter), defaultdict(Counter)
    for package, has_adjustments in packages:
        allocations = package.batch_allocations
        # Historical single-source items are attributable only without quantity
        # adjustments: even an extra receipt can have quantity_shortfall == 0.
        adjusted = bool(package.quantity_shortfall or has_adjustments)
        if allocations:
            for allocation in allocations:
                batch = allocation.production_batch_id
                if allocation.item_breakdown is not None:
                    for item in allocation.item_breakdown:
                        consumed[batch][item["size"]] += item["quantity"]
                elif len(allocations) == 1 and not adjusted:
                    for item in package.items:
                        consumed[batch][item.size] += item.quantity
                else:
                    sizes = set(actual.get(batch, {})) | {item.size for item in package.items}
                    current = Counter()
                    for item in package.items:
                        current[item.size] += item.quantity
                    for size in sizes:
                        # No inferred distribution: reserve the largest possible
                        # legacy consumption of this size from this source.
                        unknown[batch][size] += min(allocation.quantity,
                            current[size] + int(package.quantity_shortfall or 0)) if not adjusted else allocation.quantity
        elif not adjusted:
            for item in package.items:
                consumed[package.production_batch_id][item.size] += item.quantity
        else:
            batch = package.production_batch_id
            for size in set(actual.get(batch, {})) | {item.size for item in package.items}:
                unknown[batch][size] += package.total_quantity + int(package.quantity_shortfall or 0)
    return SourceSizeState(actual, dict(consumed), dict(unknown))


def _can_change_size_assignment(residual, batch: int, size: str) -> bool:
    # A reroute plus the reverse edge makes a cycle that changes two or more cells.
    start, finish = ("batch", batch), ("size", size)
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor, capacity in residual[node].items():
            if capacity <= 0 or neighbor[0] not in {"batch", "size"} or neighbor in visited:
                continue
            if node == start and neighbor == finish:
                continue
            if neighbor == finish:
                return True
            visited.add(neighbor)
            queue.append(neighbor)
    return False


def feasible_mixed_sizes(state: SourceSizeState, allocations: list[dict], items: list[dict],
                         *, check_uniqueness: bool) -> tuple[dict[int, Counter], bool]:
    """Find one feasible assignment and identify exactly determined sizes."""
    demand = Counter()
    for item in items:
        demand[item["size"]] += item["quantity"]
    source, sink = ("start",), ("finish",)
    residual = defaultdict(Counter)

    def edge(left, right, capacity):
        residual[left][right] = capacity
        residual[right][left] = 0

    for size, quantity in demand.items():
        edge(("size", size), sink, quantity)
    for allocation in allocations:
        batch, quantity = allocation["production_batch_id"], allocation["quantity"]
        edge(source, ("batch", batch), quantity)
        for size, required in demand.items():
            remaining = quantity
            if batch in state.actual:
                remaining = max(0, state.actual[batch][size] - state.consumed.get(batch, Counter())[size]
                                - state.unknown.get(batch, Counter())[size])
            edge(("batch", batch), ("size", size), min(remaining, quantity, required))

    left = sum(demand.values())
    while left:
        parents = {source: None}
        queue = deque([source])
        while queue and sink not in parents:
            node = queue.popleft()
            for neighbor, capacity in residual[node].items():
                if capacity > 0 and neighbor not in parents:
                    parents[neighbor] = node
                    queue.append(neighbor)
        if sink not in parents:
            raise HTTPException(409, "The selected Nastil quantities cannot supply the package sizes.")
        path = []
        node = sink
        while node != source:
            parent = parents[node]
            path.append((parent, node))
            node = parent
        quantity = min(residual[parent][child] for parent, child in path)
        for parent, child in path:
            residual[parent][child] -= quantity
            residual[child][parent] += quantity
        left -= quantity
    assigned = {}
    for row in allocations:
        batch = row["production_batch_id"]
        assigned[batch] = Counter({
            size: quantity for size in demand if (quantity := residual[("size", size)][("batch", batch)]) > 0
        })
    unique = check_uniqueness and not any(_can_change_size_assignment(residual, batch, size)
                                         for batch, quantities in assigned.items() for size in quantities)
    return assigned, unique


def enforce_source_sizes(db: Session, order: ProductionOrder, allocations: list[dict], items: list[dict], *,
                         exclude_package_id: int | None = None, cache: dict | None = None,
                         validate_unattributed: bool = False) -> None:
    key = ("source_item_sizes", order.id)
    state = cache.get(key) if cache is not None else None
    if state is None:
        state = source_size_state(db, order, exclude_package_id=exclude_package_id)
        if cache is not None:
            cache[key] = state
    requested = defaultdict(Counter)
    if allocations:
        for allocation in allocations:
            if allocation.get("item_breakdown") is None:
                if not validate_unattributed:
                    # Metadata-only historical edits spend no new size budget.
                    return
                batches = {row["production_batch_id"] for row in allocations}
                unresolved_in_run = cache.setdefault(("unattributed_source_batches", order.id), set()) if cache is not None else set()
                exact_items = normalized_items(items)
                by_size = {item["size"]: item for item in exact_items}
                check_uniqueness = (len(by_size) == len(exact_items) and batches <= state.actual.keys()
                                    and not (batches & unresolved_in_run)
                                    and not any(state.unknown.get(batch) for batch in batches))
                requested, unique = feasible_mixed_sizes(state, allocations, items, check_uniqueness=check_uniqueness)
                if unique:
                    for row in allocations:
                        row["item_breakdown"] = [
                            {**by_size[size], "quantity": quantity}
                            for size, quantity in sorted(requested[row["production_batch_id"]].items())
                        ]
                else:
                    unresolved_in_run.update(batches)
                break
            for item in allocation["item_breakdown"]:
                requested[allocation["production_batch_id"]][item["size"]] += item["quantity"]
    else:
        for item in items:
            requested[None][item["size"]] += item["quantity"]
    for batch, quantities in requested.items():
        if batch not in state.actual:
            continue
        for size, quantity in quantities.items():
            remaining = (state.actual[batch][size] - state.consumed.get(batch, Counter())[size]
                         - state.unknown.get(batch, Counter())[size])
            if quantity and quantity > remaining:
                raise HTTPException(409, "Package size quantity exceeds actual passed Sewing for this batch; unknown allocations may reserve its size balance")
    # The transaction-local state also accounts for earlier packages in this run.
    for batch, quantities in requested.items():
        state.consumed.setdefault(batch, Counter()).update(quantities)


def size_balance_payload(state: SourceSizeState, batch: int | None) -> dict:
    actual = state.actual.get(batch)
    known, unknown = state.consumed.get(batch, Counter()), state.unknown.get(batch, Counter())
    sizes = set(actual or {}) | set(known) | set(unknown)
    return {"actual_size_verified": actual is not None,
            "size_balances": [{"size": size, "accepted": actual[size] if actual is not None else None,
                "packaged_qty": known[size], "legacy_unknown_reserved_qty": unknown[size],
                "remaining": max(0, actual[size] - known[size] - unknown[size]) if actual is not None else None}
                for size in sorted(sizes)]}
