"""Read Sewing-ledger availability without manufacturing acceptance receipts."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, func
from sqlalchemy.orm import Session

from app.libs.enums.packaging import PackagingDepartment
from app.libs.enums.production import WorkOrderStatus
from app.schemas import Department, Package, PackageBatchAllocation, PackagingRecord, ProductionOrder, SewingRecord, WorkOrder


@dataclass(frozen=True)
class PackagingAvailableOrder:
    work_order_id: int
    production_order_id: int
    received_quantity: int
    last_received_at: datetime | None
    packing_input_quantity: int = 0
    packed_quantity: int = 0
    remaining_quantity: int = 0


def available_orders(db: Session, department: PackagingDepartment) -> list[PackagingAvailableOrder]:
    """Legacy received_quantity means proven passed output; no write occurs here.

    Dedicated batch work orders take precedence across departments. An order-wide
    work order must never borrow output routed to a different factory/Nastil.
    """
    targets = db.query(WorkOrder).join(Department, Department.id == WorkOrder.department_id).filter(
        WorkOrder.operation == "packaging", WorkOrder.status != WorkOrderStatus.CANCELLED,
        Department.code == department,
    ).all()
    order_ids = {row.production_order_id for row in targets}
    if not order_ids:
        return []
    all_targets = db.query(WorkOrder).filter(
        WorkOrder.production_order_id.in_(order_ids), WorkOrder.operation == "packaging",
        WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).order_by(WorkOrder.id.desc()).all()
    exact = {}
    shared = {}
    for row in all_targets:
        if row.production_batch_id is None:
            shared.setdefault(row.production_order_id, row.id)
        else:
            exact.setdefault((row.production_order_id, row.production_batch_id), row.id)
    sewing_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    sewing = db.query(
        WorkOrder.production_order_id, sewing_batch,
        func.sum(SewingRecord.passed_qty), func.max(SewingRecord.created_at),
    ).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id.in_(order_ids), WorkOrder.operation == "sewing",
        WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).group_by(WorkOrder.production_order_id, sewing_batch).all()
    record_batch = func.coalesce(PackagingRecord.production_batch_id, WorkOrder.production_batch_id)
    record_rows = db.query(WorkOrder.production_order_id, record_batch,
        func.sum(PackagingRecord.input_qty), func.sum(PackagingRecord.packed_qty)).join(
            WorkOrder, WorkOrder.id == PackagingRecord.work_order_id).filter(
                WorkOrder.production_order_id.in_(order_ids)).group_by(WorkOrder.production_order_id, record_batch).all()
    records = {(oid, batch): (int(inputs or 0), int(packed or 0)) for oid, batch, inputs, packed in record_rows}
    labelled = {(oid, batch): int(quantity or 0) for oid, batch, quantity in db.query(
        Package.production_order_id, PackageBatchAllocation.production_batch_id,
        func.sum(PackageBatchAllocation.quantity)).join(Package, Package.id == PackageBatchAllocation.package_id).filter(
            Package.production_order_id.in_(order_ids)).group_by(Package.production_order_id, PackageBatchAllocation.production_batch_id)}
    for oid, batch, quantity in db.query(Package.production_order_id, Package.production_batch_id,
            func.sum(Package.total_quantity + Package.quantity_shortfall)).filter(
                Package.production_order_id.in_(order_ids), ~exists().where(PackageBatchAllocation.package_id == Package.id)
            ).group_by(Package.production_order_id, Package.production_batch_id):
        labelled[(oid, batch)] = labelled.get((oid, batch), 0) + int(quantity or 0)
    sewn = {(oid, batch): (max(0, int(quantity or 0)), timestamp) for oid, batch, quantity, timestamp in sewing}
    totals: dict[int, list] = {}
    allowed = {row.id for row in targets}
    for order_id, batch_id in sewn.keys() | records.keys():
        target_id = exact.get((order_id, batch_id), shared.get(order_id))
        if target_id not in allowed:
            continue
        quantity, timestamp = sewn.get((order_id, batch_id), (0, None))
        inputs, packed = records.get((order_id, batch_id), (0, 0))
        total = totals.setdefault(target_id, [0, None, 0, 0, 0])
        total[0] += quantity
        total[1] = max(total[1], timestamp) if total[1] and timestamp else total[1] or timestamp
        total[2] += inputs
        total[3] += packed
        total[4] += max(0, quantity - inputs) + max(0, packed - labelled.get((order_id, batch_id), 0))
    service_orders = {oid for oid, source in db.query(ProductionOrder.id, ProductionOrder.source_type).filter(
        ProductionOrder.id.in_(order_ids)) if source == "usluga"}
    result = []
    for row in targets:
        if row.id not in totals:
            continue
        total = totals[row.id]
        if row.production_order_id in service_orders:
            # Usluga confirmation writes its dedicated JSON/counters and never
            # warehouse labels. It must not remain ready forever afterwards.
            confirmed = max(int(row.passed_qty or 0), int((row.service_packaging_json or {}).get("confirmed_quantity", 0)))
            total[3] = max(total[3], confirmed)
            total[4] = max(0, total[0] - total[3])
        result.append(PackagingAvailableOrder(row.id, row.production_order_id, *total))
    return result


def input_budgets(db: Session, work_order: WorkOrder) -> dict[int | None, dict[str, int]]:
    """Only actual passed Sewing less saved Packaging input is consumable.

    Historical manual/scan receipts are retained as audit history, not a second
    acceptance gate and never evidence of additional produced garments.
    """
    sewing_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    sewn = dict(db.query(sewing_batch, func.sum(SewingRecord.passed_qty)).join(
        WorkOrder, WorkOrder.id == SewingRecord.work_order_id,
    ).filter(
        WorkOrder.production_order_id == work_order.production_order_id,
        WorkOrder.operation == "sewing", WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).group_by(sewing_batch).all())
    packaging_batch = func.coalesce(PackagingRecord.production_batch_id, WorkOrder.production_batch_id)
    inputs = dict(db.query(packaging_batch, func.sum(PackagingRecord.input_qty)).join(
        WorkOrder, WorkOrder.id == PackagingRecord.work_order_id,
    ).filter(WorkOrder.id == work_order.id).group_by(packaging_batch).all())
    return {batch_id: {
        "sewing_output_qty": max(0, int(sewn.get(batch_id) or 0)),
        "input_limit_qty": max(0, int(sewn.get(batch_id) or 0)),
        "available_input_qty": max(0, int(sewn.get(batch_id) or 0) - int(inputs.get(batch_id) or 0)),
    } for batch_id in sewn.keys() | inputs.keys()}


def direct_input_budgets(db: Session, order_id: int) -> dict[int | None, dict[str, int]]:
    """Conserve passed Sewing across all Packaging WOs, including moved Nastils.

    A saved record in an earlier WO still consumed garments. Routing a new WO
    cannot make those same garments available a second time.
    """
    source_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    sewn = dict(db.query(source_batch, func.sum(SewingRecord.passed_qty)).join(
        WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
            WorkOrder.production_order_id == order_id, WorkOrder.operation == "sewing",
            WorkOrder.status != WorkOrderStatus.CANCELLED).group_by(source_batch).all())
    record_batch = func.coalesce(PackagingRecord.production_batch_id, WorkOrder.production_batch_id)
    inputs = dict(db.query(record_batch, func.sum(PackagingRecord.input_qty)).join(
        WorkOrder, WorkOrder.id == PackagingRecord.work_order_id).filter(
            WorkOrder.production_order_id == order_id).group_by(record_batch).all())
    return {batch: {"sewing_output_qty": max(0, int(sewn.get(batch) or 0)),
                    "available_input_qty": max(0, int(sewn.get(batch) or 0) - int(inputs.get(batch) or 0))}
            for batch in sewn.keys() | inputs.keys()}
