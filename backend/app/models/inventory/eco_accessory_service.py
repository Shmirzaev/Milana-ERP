"""ECO BSO accessory requirements, approval, allocation and physical issuing.

Each public mutation owns one transaction; persistence helpers share its Session.
No factory-owned material is created by a requirement or approval.
"""
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.dt import as_utc
from app.schemas import BrandedPlanningOrder, Bundle, Department, Item, Model, ProductionOrder, SewingRecord, WorkOrder
from app.schemas.inventory.eco_accessory import EcoAccessoryPlan, EcoAccessoryRequirement, EcoAccessoryAllocation
from app.schemas.inventory import eco_accessory_persistence as writes
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryPlanIn, EcoAccessoryDecisionIn, EcoAccessoryIssueIn
from app.libs.dto.inventory.eco_accessory_output import EcoAccessoryPlanOut, EcoAccessoryRequirementOut, EcoAccessoryAllocationOut
from app.libs.enums.eco_accessories import EcoAccessoryStatus as Status
from app.models.factory_scope_service import require_factory_access
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response

READ = ("eco_accessories.read", "eco_accessories.manage", "eco_accessories.approve", "eco_accessories.issue")


def _access(current, *permissions: str) -> None:
    from app.core.deps import user_permissions
    require_factory_access(current, "ECO")
    granted = user_permissions(current)
    if "*" not in granted and not set(granted).intersection(permissions):
        raise HTTPException(403, "Missing ECO accessory permission")


def eco_order_condition():
    return or_(
        ProductionOrder.id.in_(_eco_work_order_query()),
        ProductionOrder.id.in_(_eco_bundle_query()),
    )


def _eco_work_order_query():
    from sqlalchemy import select
    return select(WorkOrder.production_order_id).join(Department, Department.id == WorkOrder.department_id).where(
        WorkOrder.operation == "sewing", Department.code == "ECO", WorkOrder.status.notin_(("cancelled", "rejected")))


def _eco_bundle_query():
    from sqlalchemy import select
    return select(Bundle.production_order_id).where(Bundle.sewing_factory_code == "ECO", Bundle.status != "cancelled")


def is_eco_bso_order(db: Session, order_id: int) -> bool:
    return db.query(ProductionOrder.id).filter(ProductionOrder.id == order_id,
        ProductionOrder.planning_order_id.isnot(None), eco_order_condition()).first() is not None


def _order(db: Session, order_id: int, *, lock: bool = False):
    query = db.query(ProductionOrder).filter(ProductionOrder.id == order_id,
        ProductionOrder.planning_order_id.isnot(None), eco_order_condition())
    if lock:
        query = query.with_for_update(of=ProductionOrder).populate_existing()
    order = query.first()
    if not order or not db.get(BrandedPlanningOrder, order.planning_order_id):
        raise HTTPException(404, "ecoAccessories.orderRequired")
    return order


def _sewing_started(db: Session, order_id: int) -> bool:
    return bool(db.query(Bundle.id).filter(Bundle.production_order_id == order_id,
        Bundle.status.in_(("sent_to_sewing", "received_sewing"))).first() or db.query(SewingRecord.id)
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == order_id).first())


def _editable(db: Session, order) -> None:
    if order.status in {"completed", "finished_storage", "cancelled", "rejected"} or _sewing_started(db, order.id):
        raise HTTPException(409, "ecoAccessories.sewingStarted")


def _plan(db: Session, order_id: int, revision: int | None = None):
    plan = db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).with_for_update().populate_existing().first()
    if revision is not None and (plan.revision if plan else 0) != revision:
        raise HTTPException(409, "ecoAccessories.stale")
    return plan


def _requirements(db: Session, plan):
    return db.query(EcoAccessoryRequirement).filter_by(plan_id=plan.id).order_by(EcoAccessoryRequirement.id).all() if plan else []


def _snapshot_matches(plan, order) -> bool:
    return (plan.model_id, plan.planning_order_id, plan.planned_quantity) == (order.model_id, order.planning_order_id, order.planned_quantity)


def _output_context(db: Session, orders):
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    order_ids = [order.id for order in orders]
    plans = db.query(EcoAccessoryPlan).filter(EcoAccessoryPlan.production_order_id.in_(order_ids)).all()
    requirements = db.query(EcoAccessoryRequirement).filter(EcoAccessoryRequirement.plan_id.in_([p.id for p in plans])).all()
    allocations = db.query(EcoAccessoryAllocation, EcoMaterialBatch).join(EcoMaterialBatch,
        EcoMaterialBatch.id == EcoAccessoryAllocation.batch_id).filter(
        EcoAccessoryAllocation.requirement_id.in_([r.id for r in requirements])).order_by(EcoAccessoryAllocation.id).all()
    started = {oid for (oid,) in db.query(Bundle.production_order_id).filter(Bundle.production_order_id.in_(order_ids),
        Bundle.status.in_(("sent_to_sewing", "received_sewing"))).distinct().all()}
    started.update(oid for (oid,) in db.query(WorkOrder.production_order_id).join(SewingRecord,
        SewingRecord.work_order_id == WorkOrder.id).filter(WorkOrder.production_order_id.in_(order_ids)).distinct().all())
    return {
        "plans": {p.production_order_id: p for p in plans}, "requirements": requirements, "allocations": allocations,
        "items": {i.id: i for i in db.query(Item).filter(Item.id.in_([r.item_id for r in requirements])).all()},
        "models": {m.id: m for m in db.query(Model).filter(Model.id.in_([o.model_id for o in orders])).all()},
        "bsos": {b.id: b for b in db.query(BrandedPlanningOrder).filter(BrandedPlanningOrder.id.in_([o.planning_order_id for o in orders])).all()},
        "started": started,
    }


def _output(db: Session, order, context=None) -> EcoAccessoryPlanOut:
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    plan = context["plans"].get(order.id) if context is not None else db.query(EcoAccessoryPlan).filter_by(production_order_id=order.id).first()
    requirements = [r for r in context["requirements"] if plan and r.plan_id == plan.id] if context is not None else _requirements(db, plan)
    item_ids = [row.item_id for row in requirements]
    items = context["items"] if context is not None else {item.id: item for item in db.query(Item).filter(Item.id.in_(item_ids)).all()} if item_ids else {}
    allocations = context["allocations"] if context is not None else db.query(EcoAccessoryAllocation, EcoMaterialBatch).join(EcoMaterialBatch,
        EcoMaterialBatch.id == EcoAccessoryAllocation.batch_id).filter(
        EcoAccessoryAllocation.requirement_id.in_([row.id for row in requirements])).order_by(EcoAccessoryAllocation.id).all() if requirements else []
    lines = [EcoAccessoryRequirementOut(item_id=row.item_id, sku=items[row.item_id].sku,
        item_name=items[row.item_id].name, unit=row.unit, quantity=row.quantity,
        allocations=[EcoAccessoryAllocationOut(id=a.id, batch_id=b.id, batch_no=b.batch_no,
            quantity=a.quantity, issued_quantity=a.issued_quantity) for a, b in allocations if a.requirement_id == row.id])
        for row in requirements]
    model = context["models"].get(order.model_id) if context is not None else db.get(Model, order.model_id)
    bso = context["bsos"].get(order.planning_order_id) if context is not None else db.get(BrandedPlanningOrder, order.planning_order_id)
    return EcoAccessoryPlanOut(id=plan.id if plan else None, production_order_id=order.id,
        production_no=order.production_no, bso_no=bso.order_no, model_id=order.model_id,
        model_code=model.code if model else "", planned_quantity=order.planned_quantity,
        status=Status(plan.status) if plan else Status.DRAFT, revision=plan.revision if plan else 0,
        notes=plan.notes if plan else "", approval_notes=plan.approval_notes if plan else None,
        approved_by=plan.approved_by if plan else None, approved_at=as_utc(plan.approved_at) if plan else None,
        sewing_started=order.id in context["started"] if context is not None else _sewing_started(db, order.id), lines=lines)


def list_orders(db: Session, current, *, q: str = "", page: int = 1, page_size: int = 30) -> dict:
    _access(current, *READ)
    query = db.query(ProductionOrder).join(Model, Model.id == ProductionOrder.model_id).join(
        BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id).filter(eco_order_condition())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(ProductionOrder.production_no.ilike(like), Model.code.ilike(like), BrandedPlanningOrder.order_no.ilike(like)))
    total = query.count()
    rows = query.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    context = _output_context(db, rows) if rows else None
    return {"items": [_output(db, order, context) for order in rows], "total": total}


def get_plan(db: Session, current, order_id: int) -> EcoAccessoryPlanOut:
    _access(current, *READ)
    return _output(db, _order(db, order_id))


def item_options(db: Session, current):
    from app.libs.dto.inventory.eco_accessory_output import EcoAccessoryItemOut
    _access(current, *READ)
    return [EcoAccessoryItemOut(id=i.id, sku=i.sku, name=i.name, unit=i.unit) for i in
        db.query(Item).filter(Item.is_active.is_(True), Item.category.in_(("accessory", "packaging"))).order_by(Item.sku).all()]


def save_plan(db: Session, current, order_id: int, payload: EcoAccessoryPlanIn) -> EcoAccessoryPlanOut:
    _access(current, "eco_accessories.manage")
    order = _order(db, order_id, lock=True)
    _editable(db, order)
    plan = _plan(db, order_id, payload.revision)
    if plan and plan.status != Status.DRAFT:
        raise HTTPException(409, "ecoAccessories.draftOnly")
    lines = []
    for line in payload.lines:
        item = db.get(Item, line.item_id)
        if not item or not item.is_active or item.category not in {"accessory", "packaging"}:
            raise HTTPException(400, "ecoAccessories.accessoryRequired")
        lines.append((item.id, line.quantity, item.unit))
    old = _output(db, order).model_dump(mode="json")
    if not plan:
        plan = writes.create_plan(db, order=order, actor_id=current.id)
    writes.replace_requirements(db, plan=plan, order=order, notes=payload.notes, lines=lines)
    log_action(db, current, "save", "EcoAccessoryPlan", plan.id, old_value=old, new_value=payload.model_dump(mode="json"))
    db.commit()
    return _output(db, order)


def submit_plan(db: Session, current, order_id: int, payload: EcoAccessoryDecisionIn) -> EcoAccessoryPlanOut:
    _access(current, "eco_accessories.manage")
    order = _order(db, order_id, lock=True)
    _editable(db, order)
    plan = _plan(db, order_id, payload.revision)
    if not plan or plan.status != Status.DRAFT or not _snapshot_matches(plan, order):
        raise HTTPException(409, "ecoAccessories.draftOnly")
    writes.set_status(db, plan, Status.PENDING, notes=payload.notes)
    log_action(db, current, "submit", "EcoAccessoryPlan", plan.id)
    db.commit()
    return _output(db, order)


def approve_plan(db: Session, current, order_id: int, payload: EcoAccessoryDecisionIn) -> EcoAccessoryPlanOut:
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    from app.schemas.inventory.eco_inventory_persistence import set_batch_balance
    _access(current, "eco_accessories.approve")
    order = _order(db, order_id, lock=True)
    _editable(db, order)
    plan = _plan(db, order_id, payload.revision)
    if not plan or plan.status != Status.PENDING or not _snapshot_matches(plan, order):
        raise HTTPException(409, "ecoAccessories.pendingOnly")
    requirements = _requirements(db, plan)
    batches = db.query(EcoMaterialBatch).filter(EcoMaterialBatch.item_id.in_([r.item_id for r in requirements]),
        EcoMaterialBatch.kind == "accessory").order_by(EcoMaterialBatch.id).with_for_update().populate_existing().all() if requirements else []
    assignments = []
    for req in requirements:
        remaining = req.quantity
        item = db.get(Item, req.item_id)
        if not item or not item.is_active or item.unit != req.unit or item.category not in {"accessory", "packaging"}:
            raise HTTPException(409, "ecoAccessories.accessoryRequired")
        for batch in batches:
            if batch.item_id != req.item_id or batch.unit != req.unit:
                continue
            quantity = min(remaining, batch.quantity - batch.reserved_quantity)
            if quantity > 0:
                assignments.append((req, batch, quantity))
                remaining -= quantity
        if remaining > 0:
            raise HTTPException(409, "ecoAccessories.shortage")
    for req, batch, quantity in assignments:
        set_batch_balance(db, batch, quantity=batch.quantity, reserved_quantity=batch.reserved_quantity + quantity)
        writes.allocate(db, req.id, batch.id, quantity)
    writes.set_status(db, plan, Status.APPROVED, actor_id=current.id, notes=payload.notes)
    log_action(db, current, "approve", "EcoAccessoryPlan", plan.id,
        new_value={"allocations": [{"batch_id": b.id, "quantity": str(q)} for _, b, q in assignments]})
    db.commit()
    return _output(db, order)


def reopen_plan(db: Session, current, order_id: int, payload: EcoAccessoryDecisionIn) -> EcoAccessoryPlanOut:
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    from app.schemas.inventory.eco_inventory_persistence import set_batch_balance
    _access(current, "eco_accessories.approve")
    order = _order(db, order_id, lock=True)
    _editable(db, order)
    plan = _plan(db, order_id, payload.revision)
    if not plan or plan.status not in {Status.PENDING, Status.APPROVED}:
        raise HTTPException(409, "ecoAccessories.pendingOnly")
    requirements = _requirements(db, plan)
    allocations = db.query(EcoAccessoryAllocation).filter(EcoAccessoryAllocation.requirement_id.in_([r.id for r in requirements])).all()
    if any(row.issued_quantity > 0 for row in allocations):
        raise HTTPException(409, "ecoAccessories.alreadyIssued")
    batches = {b.id: b for b in db.query(EcoMaterialBatch).filter(EcoMaterialBatch.id.in_([a.batch_id for a in allocations]))
        .order_by(EcoMaterialBatch.id).with_for_update().populate_existing().all()} if allocations else {}
    for allocation in allocations:
        batch = batches[allocation.batch_id]
        if batch.reserved_quantity < allocation.quantity:
            raise HTTPException(409, "ecoAccessories.allocationMismatch")
    for allocation in allocations:
        batch = batches[allocation.batch_id]
        set_batch_balance(db, batch, quantity=batch.quantity, reserved_quantity=batch.reserved_quantity - allocation.quantity)
    writes.delete_allocations(db, [r.id for r in requirements])
    writes.set_status(db, plan, Status.DRAFT, notes=payload.notes)
    log_action(db, current, "reopen", "EcoAccessoryPlan", plan.id, new_value={"notes": payload.notes})
    db.commit()
    return _output(db, order)


def issue_plan(db: Session, current, order_id: int, payload: EcoAccessoryIssueIn, key: str) -> EcoAccessoryPlanOut:
    from app.models.inventory.eco_inventory_service import consume_eco_batch
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    _access(current, "eco_accessories.issue")
    order = _order(db, order_id, lock=True)
    fingerprint = {"order_id": order_id, **payload.model_dump(mode="json")}
    cached = replay_idempotent_response(db, scope="eco.accessories.issue", key=key, payload=fingerprint)
    if cached:
        return EcoAccessoryPlanOut.model_validate(cached)
    plan = _plan(db, order_id, payload.revision)
    if not plan or plan.status != Status.APPROVED or not _snapshot_matches(plan, order):
        raise HTTPException(409, "ecoAccessories.approvalRequired")
    req_ids = [r.id for r in _requirements(db, plan)]
    allocations = {a.id: a for a in db.query(EcoAccessoryAllocation).filter(EcoAccessoryAllocation.requirement_id.in_(req_ids)).all()}
    selected = []
    for line in payload.lines:
        allocation = allocations.get(line.allocation_id)
        if not allocation or line.quantity > allocation.quantity - allocation.issued_quantity:
            raise HTTPException(409, "ecoAccessories.issueExceeded")
        selected.append((allocation, line.quantity))
    # Match every other ECO stock writer's ascending batch lock order.
    db.query(EcoMaterialBatch).filter(EcoMaterialBatch.id.in_([a.batch_id for a, _ in selected])).order_by(
        EcoMaterialBatch.id).with_for_update().populate_existing().all()
    try:
        for allocation, quantity in sorted(selected, key=lambda row: row[0].batch_id):
            consume_eco_batch(db, batch_id=allocation.batch_id, quantity=quantity, current=current,
                production_order_id=order_id, reference_type="EcoAccessoryPlan", reference_id=plan.id, allocated=True, commit=False)
            writes.issue_allocation(db, allocation, quantity)
        if all(a.issued_quantity == a.quantity for a in allocations.values()):
            writes.set_status(db, plan, Status.ISSUED)
        else:
            writes.advance_revision(db, plan)
        log_action(db, current, "issue", "EcoAccessoryPlan", plan.id, new_value=fingerprint)
        result = _output(db, order)
        store_idempotent_response(db, scope="eco.accessories.issue", key=key, payload=fingerprint, response=result.model_dump(mode="json"), user=current)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def ensure_eco_accessory_approval(db: Session, order_id: int) -> dict | None:
    """Shared send/receive/start gate. Never consult Milana's accessory balance.

    Non-BSO Usluga stays on its existing path. Previously sewn orders with no new
    plan retain their historical gate; creating a plan cannot rewrite that work.
    """
    if not is_eco_bso_order(db, order_id):
        return None
    order = _order(db, order_id, lock=True)
    plan = _plan(db, order_id)
    if not plan and _sewing_started(db, order_id):
        return None
    if not plan or plan.status not in {Status.APPROVED, Status.ISSUED} or not _snapshot_matches(plan, order):
        raise HTTPException(409, "ecoAccessories.approvalRequired")
    return {"is_complete": True, "status": plan.status, "production_order_id": order_id, "sewing_gate_active": True}
