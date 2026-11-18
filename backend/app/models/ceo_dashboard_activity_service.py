"""Period output, physical finished-goods receipts, and shipment dispatches."""
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.dt import as_utc
from app.libs.dto.ceo_dashboard.report import ActivityBucket, ActivityReport, OutputRow, PackPieces, ReportWindow
from app.libs.enums.ceo_dashboard import FactoryFilter, ProductionStage
from app.libs.enums.fulfillment import ShipmentStatus
from app.libs.enums.packaging import ManualPackageSource, PackagingDepartment
from app.models.factory_scope_service import DEPARTMENT_FACTORIES
from app.schemas import (
    CuttingRecord, Department, LegacyStockReceipt, ManualPackageReceipt, Package, PackageChangeRequest,
    PackagingRecord, PrintingRecord, SewingRecord, Shipment, ShipmentPackage, WorkOrder,
)
from app.schemas.fulfillment.shipment_review import PackageQuantityAdjustment

TASHKENT = ZoneInfo("Asia/Tashkent")
UNASSIGNED = "UNASSIGNED"
STAGES = (
    (ProductionStage.CUTTING, CuttingRecord, CuttingRecord.passed_pieces),
    (ProductionStage.PRINTING, PrintingRecord, PrintingRecord.passed_qty),
    (ProductionStage.SEWING, SewingRecord, SewingRecord.passed_qty),
    (ProductionStage.PACKAGING, PackagingRecord, PackagingRecord.packed_qty),
)
PACKAGING_FACTORIES = {department.value: DEPARTMENT_FACTORIES[department.value] for department in PackagingDepartment}


def _in_window(stamp, window: ReportWindow):
    return and_(stamp >= window.lower, stamp < window.upper)


def _business_day(db: Session, stamp):
    if db.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone(TASHKENT.key, stamp))
    # SQLite rounds fractional seconds when parsing dates. Truncate before
    # shifting so a timestamp immediately before midnight stays on its day.
    return func.date(func.substr(stamp, 1, 19), "+5 hours")


def _day(value: str | date) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _production_output(db: Session, window: ReportWindow, by_day: dict[date, ActivityBucket]) -> None:
    totals = defaultdict(int)
    department = func.coalesce(func.nullif(func.upper(func.trim(Department.code)), ""), UNASSIGNED)
    for stage, model, pieces in STAGES:
        stamp = model.created_at
        if stage == ProductionStage.CUTTING:
            # An approval releases the actual passed output. Old approvals were
            # stored with a status alone, so their record timestamp is the evidence.
            stamp = func.coalesce(CuttingRecord.approved_at, CuttingRecord.created_at)
        day = _business_day(db, stamp)
        query = (
            select(day, department, func.sum(pieces))
            .select_from(model)
            .outerjoin(WorkOrder, WorkOrder.id == model.work_order_id)
            .outerjoin(Department, Department.id == WorkOrder.department_id)
            .where(_in_window(stamp, window), pieces > 0)
            .group_by(day, department)
        )
        if stage == ProductionStage.CUTTING:
            query = query.where(CuttingRecord.approval_status == "approved")
        for value, code, quantity in db.execute(query):
            bucket = by_day[_day(value)]
            totals[bucket.start, stage, code] += quantity

    for (start, stage, department_code), pieces in sorted(totals.items()):
        by_day[start].output.append(OutputRow(
            factory=DEPARTMENT_FACTORIES.get(department_code, UNASSIGNED),
            department=department_code,
            stage=stage,
            pieces=pieces,
        ))


def _package_factory():
    # The older department migration could default even a production pack to
    # PKG. Corroborate its owner from its Packaging work orders. Manual intake
    # and legacy imports used the same PKG default without a factory.
    production_source = (
        select(WorkOrder.id)
        .join(Department, Department.id == WorkOrder.department_id)
        .where(
            WorkOrder.production_order_id == Package.production_order_id,
            WorkOrder.operation == ProductionStage.PACKAGING.value,
            Department.code == Package.packaging_department_code,
            or_(
                Package.production_batch_id.is_(None),
                WorkOrder.production_batch_id.is_(None),
                WorkOrder.production_batch_id == Package.production_batch_id,
            ),
        )
        .correlate(Package)
        .exists()
    )
    packaging_source = or_(
        production_source,
        and_(
            ManualPackageReceipt.evidence["source"].as_string() == ManualPackageSource.PACKAGING.value,
            ManualPackageReceipt.evidence["packaging_department_code"].as_string() == Package.packaging_department_code,
        ),
    )
    return case(
        (and_(Package.legacy_receipt_id.is_(None), packaging_source),
         case(PACKAGING_FACTORIES, value=Package.packaging_department_code, else_=UNASSIGNED)),
        else_=UNASSIGNED,
    )


def _first_receipt_quantity():
    """Prefer saved before-values when received contents later changed."""
    edit = (
        select(PackageChangeRequest.reviewed_at.label("stamp"), PackageChangeRequest.id.label("id"),
               PackageChangeRequest.before_json["total_quantity"].as_integer().label("pieces"))
        .where(
            PackageChangeRequest.package_id == Package.id,
            PackageChangeRequest.request_type == "edit",
            PackageChangeRequest.status == "approved",
            PackageChangeRequest.reviewed_at >= Package.received_at,
        )
        .correlate(Package)
    )
    adjustment = (
        select(PackageQuantityAdjustment.created_at.label("stamp"), PackageQuantityAdjustment.id.label("id"),
               PackageQuantityAdjustment.before_json["quantity"].as_integer().label("pieces"))
        .where(
            PackageQuantityAdjustment.package_id == Package.id,
            PackageQuantityAdjustment.created_at >= Package.received_at,
        )
        .correlate(Package)
    )
    changes = edit.union_all(adjustment).subquery()
    original = (
        select(changes.c.pieces)
        .where(changes.c.pieces.isnot(None))
        .order_by(changes.c.stamp, changes.c.id)
        .limit(1)
        .scalar_subquery()
    )
    return func.coalesce(original, Package.total_quantity)


def _add(target: PackPieces, packs: int, pieces: int) -> None:
    target.packs += packs
    target.pieces += pieces


def _add_receipt(bucket: ActivityBucket, window: ReportWindow, factory: str, packs: int, pieces: int) -> None:
    if factory == UNASSIGNED:
        _add(bucket.receipts_unassigned, packs, pieces)
    if window.factory in (FactoryFilter.ALL, factory):
        _add(bucket.finished_receipts, packs, pieces)


def _receipts(db: Session, window: ReportWindow, by_day: dict[date, ActivityBucket]) -> None:
    factory = _package_factory()
    day = _business_day(db, Package.received_at)
    query = (
        select(day, factory, func.count(Package.id), func.sum(_first_receipt_quantity()))
        .select_from(Package)
        .outerjoin(ManualPackageReceipt, ManualPackageReceipt.id == Package.manual_receipt_id)
        .where(Package.legacy_receipt_id.is_(None), _in_window(Package.received_at, window))
        .group_by(day, factory)
    )
    for value, code, packs, pieces in db.execute(query):
        _add_receipt(by_day[_day(value)], window, code, packs, pieces)

    # Explicitly confirmed additional pieces are their own intake event. The
    # package was already received, so these adjustments create no pack occurrence.
    day = _business_day(db, PackageQuantityAdjustment.created_at)
    extras = (
        select(day, factory, func.sum(PackageQuantityAdjustment.extra_receipt_quantity))
        .select_from(PackageQuantityAdjustment)
        .join(Package, Package.id == PackageQuantityAdjustment.package_id)
        .outerjoin(ManualPackageReceipt, ManualPackageReceipt.id == Package.manual_receipt_id)
        .where(
            _in_window(PackageQuantityAdjustment.created_at, window),
            PackageQuantityAdjustment.created_at >= Package.received_at,
            PackageQuantityAdjustment.extra_receipt_quantity > 0,
        )
        .group_by(day, factory)
    )
    for value, code, pieces in db.execute(extras):
        _add_receipt(by_day[_day(value)], window, code, 0, pieces)

    day = _business_day(db, LegacyStockReceipt.imported_at)
    imports = (
        select(day, func.count(Package.id), func.sum(_first_receipt_quantity()))
        .select_from(LegacyStockReceipt)
        .join(Package, Package.legacy_receipt_id == LegacyStockReceipt.id)
        .where(_in_window(LegacyStockReceipt.imported_at, window))
        .group_by(day)
    )
    for value, packs, pieces in db.execute(imports):
        _add(by_day[_day(value)].legacy_imports, packs, pieces)


def _pack_quantities(rows: object) -> dict[str, int]:
    quantities = defaultdict(int)
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        number = row.get("package_no")
        quantity = row.get("quantity")
        if isinstance(quantity, str) and quantity.isascii() and quantity.isdecimal() and len(quantity) <= 10:
            quantity = int(quantity)
        if isinstance(number, str) and number.strip() and number != "—" and type(quantity) is int and quantity > 0:
            quantities[number] += quantity
    return dict(quantities)


def _dispatch_quantities(snapshot: object) -> dict[str, int]:
    document = snapshot.get("document") if isinstance(snapshot, Mapping) else None
    if not isinstance(document, Mapping):
        return {}
    return _pack_quantities(document.get("package_details")) or _pack_quantities(document.get("lines"))


def _shipments(db: Session, window: ReportWindow, by_day: dict[date, ActivityBucket]) -> None:
    shipments = select(Shipment.id, Shipment.shipped_at, Shipment.dispatch_snapshot).where(
        Shipment.deleted_at.is_(None),
        Shipment.status.in_((ShipmentStatus.SHIPPED, ShipmentStatus.DELIVERED)),
        _in_window(Shipment.shipped_at, window),
    ).order_by(Shipment.id)
    for batch in db.execute(shipments.execution_options(yield_per=200)).partitions():
        # A bounded scalar projection avoids loading package contents and repeating
        # the same frozen document for each link in a shipment.
        links = (
            select(ShipmentPackage.shipment_id, Package.package_no, ShipmentPackage.quantity, _package_factory())
            .select_from(ShipmentPackage)
            .join(Package, Package.id == ShipmentPackage.package_id)
            .outerjoin(ManualPackageReceipt, ManualPackageReceipt.id == Package.manual_receipt_id)
            .where(ShipmentPackage.shipment_id.in_([row.id for row in batch]))
        )
        by_shipment = defaultdict(dict)
        for shipment_id, package_no, quantity, factory in db.execute(links):
            by_shipment[shipment_id][package_no] = (quantity, factory)

        for shipment_id, stamp, snapshot in batch:
            bucket = by_day[as_utc(stamp).astimezone(TASHKENT).date()]
            package_links = by_shipment[shipment_id]
            quantities = _dispatch_quantities(snapshot) or {no: value[0] for no, value in package_links.items()}
            for package_no, quantity in quantities.items():
                factory = package_links.get(package_no, (0, UNASSIGNED))[1]
                if factory == UNASSIGNED:
                    _add(bucket.shipments_unassigned, 1, quantity)
                if window.factory in (FactoryFilter.ALL, factory):
                    _add(bucket.shipments, 1, quantity)


def read_activity(db: Session, window: ReportWindow) -> ActivityReport:
    buckets = [ActivityBucket(start=bucket.start, end=bucket.end) for bucket in window.buckets]
    if not buckets:
        return ActivityReport(buckets=[])
    by_day = {
        bucket.start + timedelta(days=offset): bucket
        for bucket in buckets
        for offset in range((bucket.end - bucket.start).days + 1)
    }
    _production_output(db, window, by_day)
    _receipts(db, window, by_day)
    _shipments(db, window, by_day)
    return ActivityReport(buckets=buckets)
