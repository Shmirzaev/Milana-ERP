"""Create one exact print run, optionally recording only its new Sewing input.

The existing idempotent write wrapper owns the outer commit. All evidence,
materials, counters, packages and print-run membership use its supplied Session.
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.libs.dto.fulfillment.package_workflows import PrintRunCreatePackagesIn
from app.libs.dto.packaging.tracking import PackageIn
from app.libs.dto.packaging.packaging_damage_input import PackagingDamageIn
from app.libs.dto.production.production import PackagingRecordIn
from app.libs.enums.production import WorkOrderStatus
from app.libs.enums.packaging import PackagingDepartment
from app.models.audit_service import log_action
from app.models.factory_scope_service import require_cutting_work_order_not_rejected
from app.models.numbering_service import next_package_nos
from app.models.package_workflows_service import create_run, run_payload
from app.models.packages_service import (
    PackageWriteContext, create_package, packaged_quantity_balances_by_batch,
    _packaging_record_totals_by_batch,
    prime_package_batch_memberships, prime_packaged_quantity_availability,
)
from app.models.packaging.output_service import record_output
from app.models.packaging.direct_identity_service import validate_direct_identities
from app.models.packaging.sewing_availability_service import direct_input_budgets
from app.models.packaging_scope_service import (
    require_package_source_access, require_packaging_work_order_access,
)
from app.models.workflow_service import sync_production_order_status
from app.schemas import PackagingRecord, ProductionBatch, ProductionOrder, User, WorkOrder


def _requested_sources(packages: list[PackageIn]) -> dict[int | None, int]:
    requested: dict[int | None, int] = defaultdict(int)
    for package in packages:
        total = sum(item.quantity for item in package.items)
        if total <= 0 or any(item.quantity <= 0 for item in package.items):
            raise HTTPException(400, "Package quantities must be positive")
        if package.batch_allocations:
            if any(row.quantity <= 0 for row in package.batch_allocations):
                raise HTTPException(400, "Batch allocation quantities must be > 0")
            if sum(row.quantity for row in package.batch_allocations) != total:
                raise HTTPException(400, "Batch allocation quantity must equal package total quantity")
            for row in package.batch_allocations:
                requested[row.production_batch_id] += row.quantity
        else:
            requested[package.production_batch_id] += total
    return dict(requested)


def _prepare_direct_output(db: Session, current: User, order: ProductionOrder,
                           work_order_id: int, requested: dict[int | None, int],
                           packages: list[PackageIn], owners: list[PackagingDepartment],
                           damaged_qty: int = 0) -> list[PackagingRecord]:
    # Match legacy record entry/reset: PO, Sewing WOs, Packaging WOs. This also
    # serializes a late Sewing correction and competing different request keys.
    db.query(WorkOrder).filter_by(production_order_id=order.id, operation="sewing").order_by(
        WorkOrder.id).with_for_update(of=WorkOrder).populate_existing().all()
    works = db.query(WorkOrder).filter_by(production_order_id=order.id, operation="packaging").order_by(
        WorkOrder.id).with_for_update(of=WorkOrder).populate_existing().all()
    anchor = next((row for row in works if row.id == work_order_id), None)
    if anchor is None:
        raise HTTPException(404, "Packaging work order not found for this production order")
    owner = require_packaging_work_order_access(current, db, anchor)
    if any(item.value != owner for item in owners):
        raise HTTPException(403, "Selected sources belong to another packaging department")
    if damaged_qty and len(requested) != 1:
        raise HTTPException(400, "Packaging damage requires one selected source batch")
    batch_ids = {row.id for row in db.query(ProductionBatch.id).filter_by(production_order_id=order.id)}
    if batch_ids and None in requested:
        raise HTTPException(400, "Select a production batch for this package")
    if any(batch is not None and batch not in batch_ids for batch in requested):
        raise HTTPException(404, "Production batch not found for this production order")
    active = [row for row in works if row.status != WorkOrderStatus.CANCELLED]
    targets = {}
    for batch in requested:
        exact = [row for row in active if row.production_batch_id == batch]
        shared = [row for row in active if row.production_batch_id is None]
        target = (exact or shared)[-1] if exact or shared else None
        if target is None:
            raise HTTPException(409, "No active Packaging work order owns this source")
        if require_packaging_work_order_access(current, db, target) != owner:
            raise HTTPException(403, "Selected sources belong to another packaging department")
        require_cutting_work_order_not_rejected(target)
        if target.is_blocked or anchor.is_blocked:
            raise HTTPException(409, "Packaging work order is blocked")
        if anchor.status == WorkOrderStatus.CANCELLED:
            raise HTTPException(409, "Packaging work order is cancelled")
        if target.service_packaging_json is not None:
            raise HTTPException(409, "Edit Usluga quantities through size confirmation")
        targets[batch] = target
    packed, packaged = packaged_quantity_balances_by_batch(db, order.id)
    budgets = direct_input_budgets(db, order.id)
    deficits = {}
    for batch, quantity in requested.items():
        if packaged.get(batch, 0) > packed.get(batch, 0):
            raise HTTPException(409, "Existing package quantities exceed saved Packaging evidence")
        deficit = max(0, quantity - (packed.get(batch, 0) - packaged.get(batch, 0)))
        available = budgets.get(batch, {}).get("available_input_qty", 0)
        damage = damaged_qty if len(requested) == 1 else 0
        if deficit + damage > available:
            raise HTTPException(400, f"Package quantity exceeds available passed Sewing and saved output for this source ({quantity - deficit + available})")
        deficits[batch] = deficit
    if packages:
        validate_direct_identities(db, order, packages)
    # Validate every selected source before the first material/evidence write.
    records = []
    for batch, deficit in deficits.items():
        damage = damaged_qty if len(requested) == 1 else 0
        if deficit or damage:
            target = targets[batch]
            records.append(record_output(db, current, target, PackagingRecordIn(
                work_order_id=target.id, production_batch_id=batch, input_qty=deficit + damage,
                packed_qty=deficit, damaged_qty=damage, notes="Recorded atomically with selected package labels",
            ), reconstruct_counters=True))
    return records


def create_packages_run(db: Session, current: User, payload: PrintRunCreatePackagesIn) -> dict:
    if not set(user_permissions(current)).intersection({"packaging.packages", "*"}):
        raise HTTPException(403, "Packaging permission required")
    if payload.damaged_qty and payload.work_order_id is None:
        raise HTTPException(400, "Packaging damage requires direct Packaging work order context")
    order_ids = {row.production_order_id for row in payload.packages}
    if len(order_ids) != 1:
        raise HTTPException(400, "Select one production order per packaging action")
    order = db.query(ProductionOrder).filter(ProductionOrder.id.in_(order_ids)).with_for_update().populate_existing().first()
    if order is None:
        raise HTTPException(404, "Production order not found")
    if order.source_type == "usluga":
        raise HTTPException(400, "Usluga does not enter warehouse receiving print runs")
    if any(row.model_id != order.model_id or any(item.model_id != order.model_id for item in row.items)
           for row in payload.packages):
        raise HTTPException(400, "Package model must match the production order")
    owners = require_package_source_access(current, db, order.id, payload.packages)
    if payload.work_order_id is not None and any(
            row.sales_order_id is not None and row.sales_order_id != order.sales_order_id for row in payload.packages):
        raise HTTPException(409, "Package customer order must match the production order")
    if payload.work_order_id is not None:
        _prepare_direct_output(db, current, order, payload.work_order_id, _requested_sources(payload.packages),
                               payload.packages, owners, payload.damaged_qty)
    packed = _packaging_record_totals_by_batch(db, order.id)
    if not packed:
        raise HTTPException(409, "Save Packaging output before creating packages")
    batch_ids = {batch for batch in _requested_sources(payload.packages) if batch is not None}
    context = PackageWriteContext.empty()
    context.locked_orders[order.id] = order
    prime_package_batch_memberships(db, context, production_order_id=order.id, production_batch_ids=batch_ids)
    prime_packaged_quantity_availability(db, context, production_order_id=order.id, packed_by_batch=packed)
    numbers = next_package_nos(db, len(payload.packages))
    packages = []
    for index, row in enumerate(payload.packages):
        data = {**row.model_dump(), "packaging_department_code": owners[index].value,
                "user_id": current.id, "is_admin": False, "override_capacity": False}
        package = create_package(db, **data, _write_context=context, _package_no=numbers[index],
                                 _sync_production=False, _allow_unattributed_sources=payload.work_order_id is not None)
        log_action(db, current, "create", "Package", package.id, new_value={"package_no": package.package_no})
        packages.append(package)
    sync_production_order_status(db, order.id)
    return run_payload(db, create_run(db, current, packages))


def record_damage(db: Session, current: User, payload: PackagingDamageIn) -> dict:
    if not set(user_permissions(current)).intersection({"packaging.packages", "*"}):
        raise HTTPException(403, "Packaging permission required")
    anchor = db.get(WorkOrder, payload.work_order_id)
    if anchor is None or anchor.operation != "packaging":
        raise HTTPException(404, "Packaging work order not found")
    order = db.query(ProductionOrder).filter_by(id=anchor.production_order_id).with_for_update().populate_existing().one()
    if order.source_type == "usluga":
        raise HTTPException(400, "Usluga quantities use service size confirmation")
    batch_id = payload.production_batch_id if payload.production_batch_id is not None else anchor.production_batch_id
    records = _prepare_direct_output(db, current, order, anchor.id, {batch_id: 0}, [], [], payload.damaged_qty)
    row = records[0]
    return {"id": row.id, "work_order_id": row.work_order_id,
            "production_batch_id": row.production_batch_id, "damaged_qty": row.damaged_qty}


def validate_damage_replay(db: Session, current: User, replay: dict) -> None:
    row = db.get(PackagingRecord, replay.get("id"))
    if row is None:
        raise HTTPException(410, "This Packaging damage record is no longer available")
    work = db.get(WorkOrder, row.work_order_id)
    if work is None:
        raise HTTPException(410, "This Packaging work order is no longer available")
    require_packaging_work_order_access(current, db, work)
