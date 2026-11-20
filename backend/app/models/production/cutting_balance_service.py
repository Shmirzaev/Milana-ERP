"""Project remaining Cutting stock from receipt and actual downstream evidence.

One SELECT observes all ledgers on one database snapshot. Nothing is accepted,
resized or written. Stage ledgers overlap: their quantities must never be added.
Historical partial outputs do not identify consumed labels. Such bundle counts
remain nullable, and ambiguous receipt/output overlap yields a piece range.
"""
from collections import Counter, defaultdict
from dataclasses import replace

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, and_, case, func, literal, select, union_all

from app.libs.enums.production import CuttingDepartmentCode, SewingFactoryCode, WorkOrderStatus
from app.libs.types.cutting_balance import CuttingBalanceGroup
from app.schemas import (
    Bundle, BundleScanLog, CuttingRecord, Department, Package, PackageBatchAllocation,
    PackagingRecord, PrintingRecord, SewingRecord, WorkOrder,
)


def _event(kind, **values):
    types = {"identity": Integer, "order_id": Integer, "batch_id": Integer,
             "quantity": Integer, "inputs": Integer, "outputs": Integer, "losses": Integer,
             "sizes": JSON, "factory": String, "size": String, "department": String,
             "received": Boolean, "work_order_id": Integer, "created_at": DateTime(timezone=True)}
    return select(literal(kind).label("kind"), *[
        values.get(name, literal(None, type_=dtype)).label(name) for name, dtype in types.items()
    ])


def _evidence_statement():
    receipt = Bundle.id.in_(select(BundleScanLog.bundle_id).where(
        BundleScanLog.scan_type.in_(("received_printing", "received_sewing"))))
    pending = and_(Bundle.status.in_(("created", "sent_to_printing", "sent_to_sewing")), ~receipt)
    pending_orders = select(Bundle.production_order_id).where(pending).distinct().cte("cutting_balance_orders")
    orders = select(pending_orders.c.production_order_id)
    eco_orders = select(WorkOrder.production_order_id).join(Department).where(
        WorkOrder.operation == "cutting", Department.code == "ECT").correlate(None)
    origin = case((Department.code.in_(("CUT", "ECT")), Department.code),
                  (Bundle.production_order_id.in_(eco_orders), "ECT"), else_="CUT")
    factory = func.upper(func.trim(Bundle.sewing_factory_code))
    bundles = _event("bundle", identity=Bundle.id, order_id=Bundle.production_order_id,
        batch_id=Bundle.production_batch_id, quantity=Bundle.quantity, size=Bundle.size,
        factory=case((factory.in_(("MIL", "BST", "ECO")), factory), else_="UNASSIGNED"),
        department=origin, received=~pending, work_order_id=CuttingRecord.work_order_id,
        created_at=Bundle.created_at).select_from(Bundle).outerjoin(
            CuttingRecord, CuttingRecord.id == Bundle.cutting_record_id).outerjoin(
            WorkOrder, WorkOrder.id == CuttingRecord.work_order_id).outerjoin(
            Department, Department.id == WorkOrder.department_id).where(
                Bundle.production_order_id.in_(orders), Bundle.status != "cancelled")
    ledgers = []
    for kind, cls, operation, quantity, outputs, losses in (
        ("sewing", SewingRecord, "sewing", SewingRecord.sewn_qty, SewingRecord.passed_qty,
         SewingRecord.failed_qty + SewingRecord.rejected_qty),
        ("printing", PrintingRecord, "printing", PrintingRecord.printed_qty, PrintingRecord.passed_qty,
         PrintingRecord.rejected_qty),
        ("packaging", PackagingRecord, "packaging", PackagingRecord.packed_qty,
         PackagingRecord.packed_qty, PackagingRecord.damaged_qty),
    ):
        ledgers.append(_event(kind, identity=cls.id, order_id=WorkOrder.production_order_id,
            batch_id=func.coalesce(cls.production_batch_id, WorkOrder.production_batch_id),
            quantity=quantity, inputs=cls.input_qty, outputs=outputs, losses=losses,
            sizes=cls.size_quantities if kind == "sewing" else literal(None, type_=JSON),
        ).select_from(cls).join(WorkOrder, WorkOrder.id == cls.work_order_id).where(
            WorkOrder.production_order_id.in_(orders), WorkOrder.operation == operation,
            WorkOrder.status != WorkOrderStatus.CANCELLED))
    allocated = select(PackageBatchAllocation.package_id)
    # Allocations retain the original source draw through shortfalls/dispatch.
    # Never add the package's primary batch again when allocations exist.
    labels = _event("package", identity=PackageBatchAllocation.id, order_id=Package.production_order_id,
        batch_id=PackageBatchAllocation.production_batch_id, quantity=PackageBatchAllocation.quantity,
        sizes=PackageBatchAllocation.item_breakdown,
    ).select_from(PackageBatchAllocation).join(Package, Package.id == PackageBatchAllocation.package_id).where(
        Package.production_order_id.in_(orders))
    legacy_labels = _event("package", identity=Package.id, order_id=Package.production_order_id,
        batch_id=Package.production_batch_id, quantity=Package.total_quantity + Package.quantity_shortfall,
    ).select_from(Package).where(Package.production_order_id.in_(orders), Package.id.notin_(allocated))
    return union_all(bundles, *ledgers, labels, legacy_labels)


def _size_key(value) -> str:
    return str(value or "").strip().casefold()


def _bundle_bounds(quantities: list[int], minimum: int, maximum: int) -> tuple[int, int]:
    capacity = 0
    smallest_count = 0
    for quantity in sorted(quantities, reverse=True):
        if capacity >= minimum:
            break
        smallest_count += 1
        capacity += quantity
    return smallest_count, min(len(quantities), maximum)


def reconcile_cutting_evidence(events) -> list[CuttingBalanceGroup]:
    """Pure projection, also usable against a frozen read-only audit snapshot."""
    batches = defaultdict(list)
    for row in events:
        batches[(row["order_id"], row["batch_id"])].append(row)
    result = []
    for (order_id, batch_id), rows in batches.items():
        labels = [row for row in rows if row["kind"] == "bundle"]
        if not labels:
            continue  # Never spread NULL/other-Nastil evidence onto new cuts.
        total = sum(row["quantity"] for row in labels)
        stages = defaultdict(Counter)
        known_sizes = defaultdict(Counter)
        for row in rows:
            kind = row["kind"]
            if kind == "bundle":
                continue
            for field in ("quantity", "inputs", "outputs", "losses"):
                stages[kind][field] += max(0, int(row.get(field) or 0))
            # Sewing sizes describe passed pieces only, never assumed defects.
            sizes = row.get("sizes") or []
            expected = row.get("outputs") if kind == "sewing" else row.get("quantity")
            if sizes and sum(max(0, int(size.get("quantity", 0))) for size in sizes) == expected:
                for size in sizes:
                    known_sizes[kind][_size_key(size.get("size"))] += max(0, int(size.get("quantity", 0)))
        sizes = {size for counts in known_sizes.values() for size in counts}
        raw_known = {size: max(counts[size] for counts in known_sizes.values()) for size in sizes}
        capacities = Counter()
        for row in labels:
            capacities[_size_key(row["size"])] += row["quantity"]
        known = {size: min(quantity, capacities[size]) for size, quantity in raw_known.items()}
        overflow = sum(max(0, quantity - capacities[size]) for size, quantity in raw_known.items())
        downstream_min = downstream_max = sum(known.values())
        for kind, stage in stages.items():
            quantity = max(stage["quantity"], stage["inputs"], stage["outputs"] + stage["losses"])
            stage_overflow = sum(max(0, value - capacities[size]) for size, value in known_sizes[kind].items())
            # Confirmed overproduction of M cannot silently consume untouched L.
            # A later size-unknown ledger may overlap that overflow: keep bounds.
            downstream_min = max(downstream_min, quantity - overflow)
            downstream_max = max(downstream_max, quantity - stage_overflow)
        downstream_min, downstream_max = min(total, downstream_min), min(total, downstream_max)
        received_sizes = Counter()
        for row in labels:
            if row["received"]:
                received_sizes[_size_key(row["size"])] += row["quantity"]
        batch_exit_min = max(downstream_min, sum(max(received_sizes[size], known.get(size, 0))
                                                for size in capacities))
        forced_overlap = sum(max(0, received_sizes[size] + known.get(size, 0) - capacities[size])
                             for size in capacities)
        batch_exit_max = min(total, sum(received_sizes.values()) + downstream_max - forced_overlap)
        batch_min, batch_max = max(0, total - batch_exit_max), max(0, total - batch_exit_min)
        partitions = defaultdict(list)
        for row in labels:
            partitions[(row["department"], row["factory"])].append(row)
        batch_groups = []
        for (department, factory), partition in partitions.items():
            pending = [row for row in partition if not row["received"]]
            if not pending:
                continue
            capacity = sum(row["quantity"] for row in partition)
            received = sum(row["quantity"] for row in partition if row["received"])
            if len(partitions) == 1:
                exit_min, exit_max = batch_exit_min, batch_exit_max
            else:
                # One batch split across source/destination factories has no
                # reliable output-to-label link. Preserve its possible range.
                exit_min = max(received, downstream_min - (total - capacity))
                exit_max = min(capacity, received + downstream_max)
            minimum, maximum = max(0, capacity - exit_max), max(0, capacity - exit_min)
            if maximum == 0:
                continue
            quantities = {row["identity"]: row["quantity"] for row in pending}
            bundles_min, bundles_max = _bundle_bounds(list(quantities.values()), minimum, maximum)
            batch_groups.append(CuttingBalanceGroup(
                key=f"{order_id}:{batch_id}:{department}:{factory}", order_id=order_id,
                batch_id=batch_id,
                factory=SewingFactoryCode(factory) if factory != "UNASSIGNED" else "UNASSIGNED",
                department=CuttingDepartmentCode(department),
                bundle_quantities=quantities,
                work_order_ids=frozenset(row["work_order_id"] for row in pending if row["work_order_id"] is not None),
                pieces_min=minimum, pieces_max=maximum, bundles_min=bundles_min, bundles_max=bundles_max,
                batch_pieces_min=batch_min, batch_pieces_max=batch_max, partition_bounds={},
            ))
        bounds = {group.key: (group.pieces_min, group.pieces_max) for group in batch_groups}
        result.extend(replace(group, partition_bounds=bounds) for group in batch_groups)
    return result


def cutting_balances(db) -> list[CuttingBalanceGroup]:
    return reconcile_cutting_evidence(db.execute(_evidence_statement()).mappings())


def select_balance_groups(groups: list[CuttingBalanceGroup], bundle_ids: set[int]) -> list[CuttingBalanceGroup]:
    """Search exact labels normally; adjusted batches remain indivisible facts."""
    selected = []
    for group in groups:
        matched = bundle_ids.intersection(group.bundle_quantities)
        if not matched:
            continue
        if group.adjusted:
            selected.append(group)
        else:
            quantities = {bid: group.bundle_quantities[bid] for bid in matched}
            selected.append(replace(group, bundle_quantities=quantities,
                pieces_min=sum(quantities.values()), pieces_max=sum(quantities.values()),
                bundles_min=len(quantities), bundles_max=len(quantities)))
    return selected


def balance_totals(groups: list[CuttingBalanceGroup]) -> dict:
    batches = defaultdict(list)
    for group in groups:
        batches[(group.order_id, group.batch_id)].append(group)
    pieces_min = pieces_max = 0
    for selected in batches.values():
        minimum, maximum = sum(g.pieces_min for g in selected), sum(g.pieces_max for g in selected)
        if all(g.partition_bounds.get(g.key) == (g.pieces_min, g.pieces_max) for g in selected):
            chosen = {g.key for g in selected}
            others = [bounds for key, bounds in selected[0].partition_bounds.items() if key not in chosen]
            minimum = max(minimum, selected[0].batch_pieces_min - sum(hi for lo, hi in others))
            maximum = min(maximum, selected[0].batch_pieces_max - sum(lo for lo, hi in others))
        pieces_min += minimum
        pieces_max += maximum
    bundles_min = sum(group.bundles_min for group in groups)
    bundles_max = sum(group.bundles_max for group in groups)
    capacity_min, capacity_max = _bundle_bounds([qty for group in groups for qty in group.bundle_quantities.values()],
                                               pieces_min, pieces_max)
    bundles_min, bundles_max = max(bundles_min, capacity_min), min(bundles_max, capacity_max)
    return {"source_bundles": len({bid for group in groups for bid in group.bundle_quantities}),
            "pieces": pieces_min if pieces_min == pieces_max else None,
            "pieces_min": pieces_min, "pieces_max": pieces_max,
            "bundles": bundles_min if bundles_min == bundles_max else None,
            "bundles_min": bundles_min, "bundles_max": bundles_max,
            "orders": len({group.order_id for group in groups}),
            "work_orders": len({wid for group in groups for wid in group.work_order_ids}),
            "unconfirmed_batches": sum(group.bundles is None for group in groups),
            "unresolved_batches": sum(group.pieces is None for group in groups)}


def inventory_balance_selection(db, query, scoped_query):
    """Keep scoped/searchable label navigation and batch balances consistent.

    Adjusted batches expand to their scoped original labels. Their residual is
    a batch fact, never an invented residual on an arbitrary barcode.
    """
    matched = set(db.scalars(query.with_entities(Bundle.id).statement))
    groups = cutting_balances(db)
    selected = select_balance_groups(groups, matched)
    ids = {bid for group in selected for bid in group.bundle_quantities}
    selected_query = scoped_query.filter(Bundle.id.in_(ids))
    by_bundle = {bid: group for group in selected for bid in group.bundle_quantities}
    return selected_query, balance_totals(selected), by_bundle
