"""Current, read-only physical balances for the CEO report."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, and_, case, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.core.dt import as_utc
from app.libs.dto.ceo_dashboard.report import (
    BalanceValues,
    MaterialBalanceRow,
    MaterialUnitTotal,
    MaterialVarietyRow,
    WaitingRow,
    WarehouseBalance,
    WarehouseFactoryBalance,
)
from app.libs.enums.ceo_dashboard import FactoryFilter
from app.libs.enums.inventory import StockMovementType
from app.libs.enums.packaging import PackageStatus
from app.libs.enums.production import WorkOrderStatus
from app.models.factory_scope_service import DEPARTMENT_FACTORIES, factory_for_department
from app.models.fulfillment.shipment_allocation_service import OPEN_STATUSES
from app.models.inventory_access_service import MATERIAL_CATEGORIES
from app.schemas import (
    Bundle,
    BundleScanLog,
    CuttingRecord,
    Department,
    FinishedGoodsStock,
    Item,
    Package,
    PackageItem,
    PackagePrintRun,
    PackagePrintRunMember,
    PackageScanLog,
    PackagingReceipt,
    PackagingRecord,
    PrintingRecord,
    ProductionOrder,
    SewingRecord,
    Shipment,
    ShipmentPackage,
    StockBatch,
    StockMovement,
    StockReservation,
    Warehouse,
    WarehousePackReservation,
    WorkOrder,
)
from app.schemas.inventory.eco_inventory import EcoMaterialBatch


SHARED = "SHARED"
UNASSIGNED = "UNASSIGNED"
SHARED_DEPARTMENTS = ("STR", "FGS")
INPUT_CATEGORIES = (*MATERIAL_CATEGORIES, "accessory", "packaging")
SEWING_DEPARTMENTS = {"MIL", "BST", "ECO", "SEW"}
PACKAGING_DEPARTMENTS = {"PKG", "BPK", "ECP"}
INACTIVE = (WorkOrderStatus.CANCELLED, WorkOrderStatus.REJECTED)


def _matches(location: str, factory: FactoryFilter) -> bool:
    return factory == FactoryFilter.ALL or location == factory.value


def _factory_column(department):
    return case(
        *[(department == code, location) for code, location in DEPARTMENT_FACTORIES.items()],
        (department.in_(SHARED_DEPARTMENTS), SHARED),
        else_=UNASSIGNED,
    )


def _factory_for_work(department: str | None) -> str:
    return factory_for_department(department) or UNASSIGNED


@dataclass
class _WaitingTotal:
    packs: int = 0
    bundles: int = 0
    pieces: int = 0
    oldest_since: datetime | None = None


def _add_waiting(
    totals: dict[tuple[str, str, str], _WaitingTotal],
    *, source: str, destination: str, factory: str, pieces: int,
    evidence: datetime | None, bundles: int = 0, packs: int = 0,
) -> None:
    entry = totals.setdefault((source, destination, factory), _WaitingTotal())
    entry.pieces += pieces
    entry.packs += packs
    entry.bundles += bundles
    evidence = as_utc(evidence)
    if evidence and (entry.oldest_since is None or evidence < entry.oldest_since):
        entry.oldest_since = evidence


def _bundle_waiting(db: Session, as_of: datetime, totals) -> None:
    current = aliased(Department)
    destination = aliased(Department)
    cut = aliased(Department)
    pending = (
        select(
            Bundle.id, Bundle.production_order_id, Bundle.production_batch_id,
            Bundle.status, Bundle.quantity, Bundle.created_at, Bundle.sewing_factory_code,
            current.code.label("current_department"), destination.code.label("target"),
            cut.code.label("cut_department"), CuttingRecord.approved_at,
        )
        .join(ProductionOrder, ProductionOrder.id == Bundle.production_order_id)
        .outerjoin(current, current.id == Bundle.current_department_id)
        .outerjoin(destination, destination.id == Bundle.next_department_id)
        .outerjoin(CuttingRecord, CuttingRecord.id == Bundle.cutting_record_id)
        .outerjoin(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .outerjoin(cut, cut.id == WorkOrder.department_id)
        .where(
            Bundle.status.in_(("created", "sent_to_printing", "received_printing", "sent_to_sewing")),
            ProductionOrder.status.not_in(INACTIVE),
            or_(Bundle.status != "created", Bundle.cutting_record_id.is_(None),
                CuttingRecord.approval_status == "approved"),
        )
        .cte("pending_bundles")
    )
    logs = (
        select(
            BundleScanLog.bundle_id,
            func.max(case((BundleScanLog.scan_type == "created", BundleScanLog.scanned_at))).label("created"),
            func.max(case((BundleScanLog.scan_type == "sent_printing", BundleScanLog.scanned_at))).label("sent_print"),
            func.max(case((BundleScanLog.scan_type == "received_printing", BundleScanLog.scanned_at))).label("received_print"),
            func.max(case((BundleScanLog.scan_type == "sent_sewing", BundleScanLog.scanned_at))).label("sent_sew"),
            func.max(case((and_(
                BundleScanLog.scan_type == "sent_sewing", Department.code == "PRT",
            ), 1), else_=0)).label("printing_sender"),
            func.max(case((and_(
                BundleScanLog.scan_type.in_(("sent_printing", "sent_sewing")),
                Department.code.in_(("CUT", "ECT")),
            ), Department.code))).label("cutting_sender"),
        )
        .join(pending, pending.c.id == BundleScanLog.bundle_id)
        .outerjoin(Department, Department.id == BundleScanLog.from_department_id)
        .where(BundleScanLog.scanned_at <= as_of)
        .group_by(BundleScanLog.bundle_id)
        .subquery()
    )
    printed = defaultdict(list)
    for row in db.execute(
        select(pending, logs.c.created, logs.c.sent_print, logs.c.received_print,
               logs.c.sent_sew, logs.c.printing_sender, logs.c.cutting_sender)
        .outerjoin(logs, logs.c.bundle_id == pending.c.id)
    ):
        direct_sewing_target = row.target if row.target in SEWING_DEPARTMENTS else row.sewing_factory_code
        cutting_department = row.cut_department
        if cutting_department not in ("CUT", "ECT"):
            cutting_department = (
                row.current_department if row.current_department in ("CUT", "ECT")
                else row.cutting_sender or UNASSIGNED
            )
        if row.status == "received_printing" or (
            row.status == "sent_to_sewing" and (row.received_print or row.printing_sender)
        ):
            if direct_sewing_target not in SEWING_DEPARTMENTS:
                direct_sewing_target = "SEW"
            printed[(row.production_order_id, row.production_batch_id)].append((row, direct_sewing_target))
            continue
        if row.status == "sent_to_printing" or row.status == "created" and row.target == "PRT":
            target = "PRT"
            evidence = row.sent_print if row.status == "sent_to_printing" else row.created or row.created_at
        elif row.status == "sent_to_sewing" or row.status == "created" and row.target in SEWING_DEPARTMENTS:
            target = direct_sewing_target if direct_sewing_target in SEWING_DEPARTMENTS else "SEW"
            evidence = row.sent_sew if row.status == "sent_to_sewing" else row.created or row.created_at
        else:
            continue
        if row.status == "created":
            approval = as_utc(row.approved_at)
            evidence = as_utc(evidence)
            if approval and (evidence is None or approval > evidence):
                evidence = approval
        _add_waiting(
            totals, source=cutting_department, destination=target, factory=_factory_for_work(cutting_department),
            pieces=row.quantity, bundles=1, evidence=evidence,
        )

    if printed:
        _printing_waiting(db, as_of, totals, printed)


def _printing_waiting(db: Session, as_of: datetime, totals, pending) -> None:
    """Printed records are batch-level and cannot identify which bundle had a reject."""
    orders = {order for order, _ in pending}
    # Joining to set-valued SQL avoids one query per order. Limit the historical
    # lookups to orders with an active Printing handoff.
    batch = func.coalesce(PrintingRecord.production_batch_id, WorkOrder.production_batch_id)
    output = {
        (order, batch_id): (int(passed), oldest)
        for order, batch_id, passed, oldest in db.execute(
            select(WorkOrder.production_order_id, batch, func.sum(PrintingRecord.passed_qty), func.min(PrintingRecord.created_at))
            .join(WorkOrder, WorkOrder.id == PrintingRecord.work_order_id)
            .where(WorkOrder.production_order_id.in_(orders), WorkOrder.operation == "printing",
                   WorkOrder.status.not_in(INACTIVE), PrintingRecord.passed_qty > 0, PrintingRecord.created_at <= as_of)
            .group_by(WorkOrder.production_order_id, batch)
        )
    }
    received_at_printing = Bundle.scan_logs.any(BundleScanLog.scan_type == "received_printing")
    sewing_receipts = {
        (order, batch_id): int(quantity)
        for order, batch_id, quantity in db.execute(
            select(Bundle.production_order_id, Bundle.production_batch_id, func.sum(Bundle.quantity))
            .where(Bundle.production_order_id.in_(orders), Bundle.status == "received_sewing", received_at_printing)
            .group_by(Bundle.production_order_id, Bundle.production_batch_id)
        )
    }
    for key, rows in pending.items():
        passed, oldest_output = output.get(key, (0, None))
        sewing_received = sewing_receipts.get(key, 0)
        sent = [(row, target) for row, target in rows if row.status == "sent_to_sewing"]
        # Scanned transfers have label-level quantities. When printed records
        # cover the whole queued balance, display only known passed pieces.
        # Multiple destinations cannot share an unattributed batch adjustment.
        targets = {target for _, target in rows}
        if len(targets) == 1 and passed:
            target = next(iter(targets))
            label_quantity = sum(row.quantity for row, _ in rows)
            pieces = min(max(0, passed - sewing_received), label_quantity)
            if pieces:
                allocated_bundles = len(rows) if pieces == label_quantity or len(rows) == 1 else len(sent)
                events = [as_utc(row.sent_sew) for row, _ in sent if row.sent_sew]
                if len(sent) != len(rows) and not sewing_received and oldest_output:
                    events.append(as_utc(oldest_output))
                _add_waiting(
                    totals, source="PRT", destination=target, factory=_factory_for_work("PRT"),
                    pieces=pieces, bundles=allocated_bundles, evidence=min(events) if events else None,
                )
            continue
        for row, target in sent:
            _add_waiting(
                totals, source="PRT", destination=target, factory=_factory_for_work("PRT"),
                pieces=row.quantity, bundles=1, evidence=row.sent_sew,
            )


def _sewing_waiting(db: Session, as_of: datetime, totals) -> None:
    source = aliased(Department)
    target = aliased(Department)
    sewing_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    dated_output = case((SewingRecord.correction_version == 0, SewingRecord.created_at))
    sewing = (
        select(WorkOrder.production_order_id.label("order_id"), sewing_batch.label("batch_id"),
               func.min(source.code).label("source"), func.count(func.distinct(source.code)).label("routes"),
               func.sum(SewingRecord.passed_qty).label("pieces"), func.min(dated_output).label("oldest"),
               func.max(dated_output).label("newest"), func.count(dated_output).label("dated_records"),
               func.count(SewingRecord.id).label("output_records"))
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .join(source, source.id == WorkOrder.department_id)
        .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
        .where(WorkOrder.operation == "sewing", WorkOrder.status.not_in(INACTIVE),
               ProductionOrder.status.not_in(INACTIVE), SewingRecord.passed_qty > 0, SewingRecord.created_at <= as_of)
        .group_by(WorkOrder.production_order_id, sewing_batch)
        .cte("unconsumed_sewing")
    )
    packaging_batch = func.coalesce(PackagingRecord.production_batch_id, WorkOrder.production_batch_id)
    consumed = (
        select(WorkOrder.production_order_id.label("order_id"), packaging_batch.label("batch_id"),
               func.sum(PackagingRecord.input_qty).label("pieces"))
        .join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id)
        .where(PackagingRecord.input_qty > 0)
        .group_by(WorkOrder.production_order_id, packaging_batch)
        .subquery()
    )
    receipts = (
        select(PackagingReceipt.production_order_id.label("order_id"), PackagingReceipt.production_batch_id.label("batch_id"),
               func.sum(PackagingReceipt.quantity).label("pieces"))
        .group_by(PackagingReceipt.production_order_id, PackagingReceipt.production_batch_id)
        .subquery()
    )
    packaging_id = (
        select(WorkOrder.id)
        .where(WorkOrder.production_order_id == sewing.c.order_id, WorkOrder.operation == "packaging",
               WorkOrder.status.not_in(INACTIVE),
               or_(WorkOrder.production_batch_id == sewing.c.batch_id, WorkOrder.production_batch_id.is_(None)))
        .order_by(WorkOrder.production_batch_id.is_not(None).desc(), WorkOrder.id.desc())
        .limit(1)
        .correlate(sewing)
        .scalar_subquery()
    )
    recorded = func.coalesce(consumed.c.pieces, 0)
    explicitly_received = func.coalesce(receipts.c.pieces, 0)
    for row in db.execute(
        select(sewing, target.code.label("target"), recorded.label("consumed"),
               explicitly_received.label("received"), ProductionOrder.source_type,
               WorkOrder.passed_qty.label("service_passed"), WorkOrder.service_packaging_json)
        .select_from(sewing)
        .join(WorkOrder, WorkOrder.id == packaging_id)
        .join(target, target.id == WorkOrder.department_id)
        .join(ProductionOrder, ProductionOrder.id == sewing.c.order_id)
        .outerjoin(consumed, and_(consumed.c.order_id == sewing.c.order_id,
                                  consumed.c.batch_id.is_not_distinct_from(sewing.c.batch_id)))
        .outerjoin(receipts, and_(receipts.c.order_id == sewing.c.order_id,
                                  receipts.c.batch_id.is_not_distinct_from(sewing.c.batch_id)))
        .where(target.code.in_(PACKAGING_DEPARTMENTS), sewing.c.pieces > recorded,
               sewing.c.pieces > explicitly_received)
    ):
        handled = max(int(row.consumed), int(row.received))
        if row.source_type == "usluga":
            handled = max(handled, int(row.service_passed or 0), int((row.service_packaging_json or {}).get("confirmed_quantity", 0)))
        remaining = int(row.pieces) - handled
        if remaining > 0:
            department = row.source if row.routes == 1 and row.source in SEWING_DEPARTMENTS else "SEW"
            factory = _factory_for_work(row.source) if row.routes == 1 else UNASSIGNED
            # A partial handoff has an exact remaining age only when all
            # proven output in that scope has the same timestamp.
            single_age = row.dated_records == row.output_records and row.oldest == row.newest
            _add_waiting(totals, source=department, destination=row.target, factory=factory,
                         pieces=remaining, evidence=row.oldest if handled == 0 or single_age else None)


def _packaging_waiting(db: Session, as_of: datetime, totals) -> None:
    eligible = (
        select(Package.id, Package.packaging_department_code, Package.status,
               Package.total_quantity, Package.packed_at)
        .join(ProductionOrder, ProductionOrder.id == Package.production_order_id)
        .where(Package.status.in_((PackageStatus.PACKED, PackageStatus.RETURNED)),
               Package.total_quantity > 0, Package.received_at.is_(None), ProductionOrder.status.not_in(INACTIVE),
               ProductionOrder.source_type != "usluga")
        .cte("pending_packages")
    )
    returns = (
        select(PackageScanLog.package_id, func.max(PackageScanLog.scanned_at).label("returned_at"))
        .join(eligible, eligible.c.id == PackageScanLog.package_id)
        .where(PackageScanLog.scan_type == PackageStatus.RETURNED.value, PackageScanLog.scanned_at <= as_of)
        .group_by(PackageScanLog.package_id)
        .subquery()
    )
    reissues = (
        select(PackagePrintRunMember.package_id, func.min(PackagePrintRun.created_at).label("reissued_at"))
        .join(PackagePrintRun, PackagePrintRun.id == PackagePrintRunMember.run_id)
        .join(returns, returns.c.package_id == PackagePrintRunMember.package_id)
        .where(PackagePrintRun.created_at > returns.c.returned_at, PackagePrintRun.created_at <= as_of)
        .group_by(PackagePrintRunMember.package_id)
        .subquery()
    )
    for department, status, packs, pieces, oldest in db.execute(
        select(eligible.c.packaging_department_code, eligible.c.status, func.count(eligible.c.id),
               func.sum(eligible.c.total_quantity), func.min(case(
                   (eligible.c.status == PackageStatus.RETURNED, returns.c.returned_at),
                   (returns.c.returned_at.is_not(None), reissues.c.reissued_at),
                   else_=case((eligible.c.packed_at <= as_of, eligible.c.packed_at)),
               )))
        .select_from(eligible)
        .outerjoin(returns, returns.c.package_id == eligible.c.id)
        .outerjoin(reissues, reissues.c.package_id == eligible.c.id)
        .group_by(eligible.c.packaging_department_code, eligible.c.status)
    ):
        source, destination = ("FGS", department) if status == PackageStatus.RETURNED else (department, "FGS")
        _add_waiting(totals, source=source, destination=destination, factory=_factory_for_work(department),
                     pieces=int(pieces), packs=int(packs), evidence=oldest)


def _waiting(db: Session, as_of: datetime, factory: FactoryFilter) -> list[WaitingRow]:
    totals: dict[tuple[str, str, str], _WaitingTotal] = {}
    _bundle_waiting(db, as_of, totals)
    _sewing_waiting(db, as_of, totals)
    _packaging_waiting(db, as_of, totals)
    return [
        WaitingRow(source=source, destination=destination, factory=location, pieces=amount.pieces,
                   packs=amount.packs, bundles=amount.bundles, oldest_since=amount.oldest_since)
        for (source, destination, location), amount in sorted(totals.items())
        if _matches(location, factory)
    ]

def _warehouse(db: Session, factory: FactoryFilter) -> WarehouseBalance:
    remaining = Package.total_quantity - Package.dispatched_quantity
    location = _factory_column(Department.code)
    received = (
        select(Package.id, Package.status, location.label("factory"), remaining.label("pieces"),
               WarehousePackReservation.id.label("warehouse_hold"))
        .select_from(Package)
        .outerjoin(Warehouse, Warehouse.id == Package.warehouse_id)
        .outerjoin(Department, Department.id == Warehouse.department_id)
        .outerjoin(WarehousePackReservation, WarehousePackReservation.package_id == Package.id)
        .outerjoin(ProductionOrder, ProductionOrder.id == Package.production_order_id)
        .where(
            remaining > 0,
            or_(ProductionOrder.id.is_(None), ProductionOrder.source_type != "usluga"),
            or_(
                Package.status == PackageStatus.RECEIVED,
                and_(Package.status == PackageStatus.RESERVED, or_(
                    Package.received_at.is_not(None), Package.legacy_receipt_id.is_not(None),
                    Package.manual_receipt_id.is_not(None), WarehousePackReservation.id.is_not(None),
                )),
            ),
        )
    )
    if factory != FactoryFilter.ALL:
        received = received.where(location == factory.value)
    physical = received.cte("physical_packages")
    stock_holds = (
        select(FinishedGoodsStock.package_id.label("package_id"), func.sum(FinishedGoodsStock.reserved_qty).label("pieces"))
        .join(physical, physical.c.id == FinishedGoodsStock.package_id)
        .where(FinishedGoodsStock.reserved_qty > 0)
        .group_by(FinishedGoodsStock.package_id)
        .subquery()
    )
    reserved = case(
        (physical.c.warehouse_hold.is_not(None), physical.c.pieces),
        (and_(physical.c.status == PackageStatus.RESERVED, stock_holds.c.pieces.is_(None)), physical.c.pieces),
        (stock_holds.c.pieces >= physical.c.pieces, physical.c.pieces),
        else_=func.coalesce(stock_holds.c.pieces, 0),
    )
    packs_at_location = (
        select(physical.c.id, physical.c.factory, physical.c.pieces, reserved.label("reserved"))
        .outerjoin(stock_holds, stock_holds.c.package_id == physical.c.id)
        .cte("warehouse_package_balances")
    )
    additional = _open_shipment_holds(db, packs_at_location)
    by_factory = [
        WarehouseFactoryBalance(factory=code, packs=int(packs), pieces=int(pieces),
                                available_pieces=int(pieces - held_pieces - additional[code]),
                                reserved_pieces=int(held_pieces + additional[code]))
        for code, packs, pieces, held_pieces in db.execute(
            select(packs_at_location.c.factory, func.count(packs_at_location.c.id),
                   func.sum(packs_at_location.c.pieces), func.sum(packs_at_location.c.reserved))
            .group_by(packs_at_location.c.factory)
            .order_by(packs_at_location.c.factory)
        )
    ]
    return WarehouseBalance(
        packs=sum(row.packs for row in by_factory),
        pieces=sum(row.pieces for row in by_factory),
        available_pieces=sum(row.available_pieces for row in by_factory),
        reserved_pieces=sum(row.reserved_pieces for row in by_factory),
        by_factory=by_factory,
    )


def _open_shipment_holds(db: Session, packs) -> dict[str, int]:
    """Union open allocations with physical stock holds by sales order and variant."""
    open_links = (
        select(
            packs.c.id, packs.c.factory, packs.c.pieces, packs.c.reserved, Shipment.sales_order_id,
            ShipmentPackage.quantity, Shipment.dispatch_snapshot, Package.dispatched_quantities,
        )
        .select_from(packs)
        .join(Package, Package.id == packs.c.id)
        .join(ShipmentPackage, ShipmentPackage.package_id == packs.c.id)
        .join(Shipment, Shipment.id == ShipmentPackage.shipment_id)
        .where(Shipment.status.in_(OPEN_STATUSES), Shipment.deleted_at.is_(None), packs.c.reserved < packs.c.pieces)
    ).cte("open_warehouse_allocations")
    claims = db.execute(select(open_links)).all()
    if not claims:
        return defaultdict(int)
    # Read detail only for packages where a sales reservation might already
    # cover some or all of an open shipment's selected pieces.
    matchable = select(open_links.c.id, open_links.c.sales_order_id).where(
        open_links.c.reserved > 0, open_links.c.sales_order_id.is_not(None),
    ).distinct().cte("matchable_warehouse_allocations")
    variant_holds: dict[tuple[int, int], dict[tuple[int | None, str, str], int]] = defaultdict(dict)
    stock = FinishedGoodsStock
    reservations = db.execute(
        select(stock.package_id, StockReservation.sales_order_id, stock.model_id, stock.color, stock.size,
               func.sum(StockReservation.quantity))
        .select_from(StockReservation)
        .join(stock, stock.id == StockReservation.finished_goods_stock_id)
        .join(matchable, and_(matchable.c.id == stock.package_id,
                              matchable.c.sales_order_id == StockReservation.sales_order_id))
        .where(stock.reserved_qty > 0)
        .group_by(stock.package_id, StockReservation.sales_order_id, stock.model_id, stock.color, stock.size)
    )
    for pid, sale, model, color, size, quantity in reservations:
        variant_holds[(pid, sale)][(model, color, size)] = int(quantity)
    items = defaultdict(dict)
    if variant_holds:
        for item in db.scalars(
            select(PackageItem).where(PackageItem.package_id.in_(
                select(matchable.c.id),
            ))
        ):
            items[item.package_id][str(item.id)] = (item.quantity, (item.model_id, item.color, item.size))

    claim_pieces: dict[int, int] = defaultdict(int)
    capacities = {}
    confirmed_overlap: dict[tuple[int, int], dict[tuple[int | None, str, str], int]] = defaultdict(lambda: defaultdict(int))
    whole_pack_sales = set()
    for row in claims:
        pid = row.id
        claim_pieces[pid] += int(row.quantity)
        capacities[pid] = (row.factory, int(row.pieces), int(row.reserved))
        order_key = (pid, row.sales_order_id)
        if order_key not in variant_holds:
            continue
        snapshot = row.dispatch_snapshot if isinstance(row.dispatch_snapshot, dict) else {}
        frozen = snapshot.get("package_quantities")
        selected = frozen.get(str(pid)) if isinstance(frozen, dict) else None
        if selected is None and row.quantity == row.pieces:
            whole_pack_sales.add(order_key)
            continue
        package_items = items[pid]
        dispatched = row.dispatched_quantities if isinstance(row.dispatched_quantities, dict) else {}
        if not isinstance(selected, dict) or selected.keys() != package_items.keys() or any(
            type(quantity) is not int or quantity < 0 or type(dispatched.get(key, 0)) is not int
            or quantity > package_items[key][0] - dispatched.get(key, 0)
            for key, quantity in selected.items()
        ) or sum(selected.values()) != row.quantity:
            # Historical partial links can lack an exact split. Count their
            # claim without guessing which other hold it overlaps.
            continue
        for item_id, quantity in selected.items():
            confirmed_overlap[order_key][package_items[item_id][1]] += quantity

    overlap_by_pack: dict[int, int] = defaultdict(int)
    for key, holds in variant_holds.items():
        pid, _ = key
        if key in whole_pack_sales:
            overlap_by_pack[pid] += sum(holds.values())
        else:
            overlap_by_pack[pid] += sum(min(amount, holds.get(variant, 0)) for variant, amount in confirmed_overlap[key].items())

    result: dict[str, int] = defaultdict(int)
    for pid, (factory, pieces, reserved) in capacities.items():
        overlap = min(overlap_by_pack[pid], reserved, claim_pieces[pid])
        result[factory] += min(pieces - reserved, claim_pieces[pid] - overlap)
    return result


_MATERIAL_IN = (
    StockMovementType.PRODUCE, StockMovementType.RETURN, StockMovementType.ADJUSTMENT, StockMovementType.TRANSFER,
)
_MATERIAL_OUT = (
    StockMovementType.ISSUE, StockMovementType.CONSUME, StockMovementType.WASTE,
    StockMovementType.SHIPMENT, StockMovementType.TRANSFER,
)


def _materials_sql():
    location = _factory_column(Department.code)
    common = (
        Item.category.in_(INPUT_CATEGORIES),
        StockMovement.batch_id.is_(None),
    )
    stock = (
        select(StockBatch.item_id, StockBatch.warehouse_id, Warehouse.name.label("warehouse"), location.label("factory"),
               StockBatch.unit, func.sum(StockBatch.quantity).label("quantity"), func.count(StockBatch.id).label("batches"))
        .join(Item, Item.id == StockBatch.item_id)
        .join(Warehouse, Warehouse.id == StockBatch.warehouse_id)
        .outerjoin(Department, Department.id == Warehouse.department_id)
        .where(Item.category.in_(INPUT_CATEGORIES), StockBatch.quantity > 0, StockBatch.archived_at.is_(None))
        .group_by(StockBatch.item_id, StockBatch.warehouse_id, Warehouse.name, location, StockBatch.unit)
    )
    # Batch-linked movements are already reflected in StockBatch.quantity.
    # An unbatched transfer supplies a debit and a credit in the same unit.
    directions = []
    for warehouse_id, types, sign in (
        (StockMovement.to_warehouse_id, _MATERIAL_IN, 1),
        (StockMovement.from_warehouse_id, _MATERIAL_OUT, -1),
    ):
        directions.append(
            select(StockMovement.item_id, warehouse_id, Warehouse.name, location, StockMovement.unit,
                   func.sum(StockMovement.quantity) * sign, literal(0))
            .select_from(StockMovement)
            .join(Item, Item.id == StockMovement.item_id)
            .outerjoin(Warehouse, Warehouse.id == warehouse_id)
            .outerjoin(Department, Department.id == Warehouse.department_id)
            .where(*common, StockMovement.movement_type.in_(types),
                   or_(StockMovement.movement_type != StockMovementType.TRANSFER,
                       and_(StockMovement.from_warehouse_id.is_not(None), StockMovement.to_warehouse_id.is_not(None))))
            .group_by(StockMovement.item_id, warehouse_id, Warehouse.name, location, StockMovement.unit)
        )

    eco_warehouses = (
        select(Warehouse.id, Warehouse.name)
        .join(Department, Department.id == Warehouse.department_id)
        .where(Department.code.in_(("ECO", "ECT", "ECP")))
        .subquery()
    )
    eco_id = cast(EcoMaterialBatch.receipt_details["warehouse_id"].as_string(), String)
    eco = (
        select(EcoMaterialBatch.item_id, eco_warehouses.c.id, eco_warehouses.c.name, literal(FactoryFilter.ECO.value),
               EcoMaterialBatch.unit, func.sum(EcoMaterialBatch.quantity), func.count(EcoMaterialBatch.id))
        .select_from(EcoMaterialBatch)
        .outerjoin(eco_warehouses, cast(eco_warehouses.c.id, String) == eco_id)
        .where(EcoMaterialBatch.quantity > 0)
        .group_by(EcoMaterialBatch.item_id, eco_warehouses.c.id, eco_warehouses.c.name, EcoMaterialBatch.unit)
    )
    return union_all(stock, *directions, eco).subquery()


@dataclass
class _MaterialsTotal:
    quantity: Decimal = Decimal(0)
    batches: int = 0
    items: set[int] = field(default_factory=set)

    def add(self, item_id: int, quantity: Decimal, batches: int) -> None:
        self.quantity += quantity
        self.batches += batches
        if quantity > 0:
            self.items.add(item_id)


def _materials(db: Session, factory: FactoryFilter) -> tuple[
    list[MaterialBalanceRow], list[MaterialUnitTotal], list[MaterialVarietyRow],
]:
    balances = _materials_sql()
    normalized = func.lower(func.trim(balances.c.unit))
    unit = case((normalized.in_(("kg", "kilogram", "kilograms")), "kg"), else_=normalized)
    query = (
        select(Item.id, Item.name, Item.sku, balances.c.warehouse_id, balances.c.warehouse, balances.c.factory, unit,
               func.sum(balances.c.quantity), func.sum(balances.c.batches))
        .select_from(balances)
        .join(Item, Item.id == balances.c.item_id)
        .group_by(Item.id, Item.name, Item.sku, balances.c.warehouse_id, balances.c.warehouse, balances.c.factory, unit)
    )
    if factory != FactoryFilter.ALL:
        query = query.where(balances.c.factory == factory.value)
    by_warehouse: dict[tuple[str, int | None, str, str], _MaterialsTotal] = defaultdict(_MaterialsTotal)
    by_unit: dict[str, _MaterialsTotal] = defaultdict(_MaterialsTotal)
    by_item: dict[tuple[str, str, str], _MaterialsTotal] = defaultdict(_MaterialsTotal)
    for item_id, item, sku, warehouse_id, warehouse, location, unit_name, quantity, batches in db.execute(query):
        unit_name = unit_name or UNASSIGNED
        if not warehouse:
            warehouse = "ECO_LEDGER" if location == FactoryFilter.ECO.value else UNASSIGNED
        by_warehouse[(location, warehouse_id, warehouse, unit_name)].add(item_id, quantity, batches)
        by_unit[unit_name].add(item_id, quantity, batches)
        by_item[(item, sku, unit_name)].add(item_id, quantity, batches)
    material_rows = [
        MaterialBalanceRow(warehouse=warehouse, factory=location, unit=unit_name, quantity=max(Decimal(0), amount.quantity),
                           active_batches=amount.batches, varieties=len(amount.items))
        for (location, _, warehouse, unit_name), amount in sorted(
            by_warehouse.items(), key=lambda pair: (pair[0][0], pair[0][2], pair[0][3], pair[0][1] or 0))
        if amount.quantity > 0 or amount.batches
    ]
    material_totals = [
        MaterialUnitTotal(unit=unit_name, quantity=max(Decimal(0), amount.quantity),
                          active_batches=amount.batches, varieties=len(amount.items))
        for unit_name, amount in sorted(by_unit.items()) if amount.quantity > 0 or amount.batches
    ]
    varieties = [
        MaterialVarietyRow(item=item, sku=sku, unit=unit_name, quantity=max(Decimal(0), amount.quantity),
                           active_batches=amount.batches)
        for (item, sku, unit_name), amount in sorted(by_item.items()) if amount.quantity > 0 or amount.batches
    ]
    return material_rows, material_totals, varieties


def read_live_balances(db: Session, as_of: datetime, factory: FactoryFilter) -> BalanceValues:
    """Read mutable ledgers at the caller's consistent current snapshot."""
    materials, material_totals, material_varieties = _materials(db, factory)
    return BalanceValues(
        waiting=_waiting(db, as_of, factory),
        warehouse=_warehouse(db, factory),
        materials=materials,
        material_totals=material_totals,
        material_varieties=material_varieties,
    )
