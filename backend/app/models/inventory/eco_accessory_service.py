"""ECO BSO accessory requirements, approval, allocation and physical issuing.

Each public mutation owns one transaction; persistence helpers share its Session.
No factory-owned material is created by a requirement or approval.
"""
from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.core.dt import as_utc
from app.schemas import BrandedPlanningOrder, Bundle, Department, Item, Model, ProductionOrder, SewingAssignment, SewingFlow, SewingRecord, WorkOrder
from app.schemas.inventory.eco_accessory import EcoAccessoryPlan, EcoAccessoryRequirement, EcoAccessoryAllocation
from app.schemas.inventory import eco_accessory_persistence as writes
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryPlanIn, EcoAccessoryDecisionIn, EcoAccessoryIssueIn
from app.libs.dto.inventory.eco_accessory_output import EcoAccessoryPlanOut, EcoAccessoryRequirementOut, EcoAccessoryAllocationOut
from app.libs.enums.eco_accessories import EcoAccessoryStatus as Status
from app.libs.enums.production import SewingFactoryCode
from app.models.factory_scope_service import require_factory_access
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response

READ = ("eco_accessories.read", "eco_accessories.manage", "eco_accessories.approve", "eco_accessories.issue")
ACTIVE_ASSIGNMENT_STATUSES = ("planned", "in_progress", "completed")


def canonical_sewing_factory(value: str | None) -> SewingFactoryCode:
    from app.models.bundles_service import SEWING_FACTORY_ALIASES
    normalized = str(value or "").strip().upper()
    if normalized in {"", "SEW"}:
        return SewingFactoryCode.MILANA
    code = SEWING_FACTORY_ALIASES.get(normalized)
    if code is None:
        raise HTTPException(400, "Unknown sewing factory; correct the stored factory before continuing")
    return SewingFactoryCode(code)


def _factory_condition(column, factories: set[SewingFactoryCode]):
    from app.models.bundles_service import SEWING_FACTORY_ALIASES
    aliases = {alias for alias, code in SEWING_FACTORY_ALIASES.items() if code in factories}
    if SewingFactoryCode.MILANA in factories:
        aliases.update(("", "SEW"))
    return func.upper(func.trim(func.coalesce(column, ""))).in_(sorted(aliases))


def _access(current, *permissions: str) -> None:
    from app.core.deps import user_permissions
    from app.models.inventory_access_service import require_accessories
    require_factory_access(current, "ECO")
    require_accessories(current)
    granted = user_permissions(current)
    if "*" not in granted and not set(granted).intersection(permissions):
        raise HTTPException(403, "Missing ECO accessory permission")


def eco_order_condition():
    return or_(
        ProductionOrder.id.in_(_eco_work_order_query()),
        ProductionOrder.id.in_(_eco_bundle_query()),
        ProductionOrder.id.in_(_eco_assigned_order_query()),
        ProductionOrder.id.in_(_direct_flow_query().with_only_columns(WorkOrder.production_order_id).where(
            _factory_condition(SewingFlow.factory_code, {SewingFactoryCode.ECO_COTTON}))),
    )


def _eco_work_order_query():
    from sqlalchemy import select
    return select(WorkOrder.production_order_id).join(Department, Department.id == WorkOrder.department_id).where(
        WorkOrder.operation == "sewing", _factory_condition(Department.code, {SewingFactoryCode.ECO_COTTON}),
        WorkOrder.status.notin_(("cancelled", "rejected")))


def _eco_bundle_query():
    from sqlalchemy import select
    return select(Bundle.production_order_id).where(
        _factory_condition(Bundle.sewing_factory_code, {SewingFactoryCode.ECO_COTTON}), Bundle.status != "cancelled")


def _active_assignment_query():
    from sqlalchemy import select
    return select(WorkOrder.id.label("work_id"), WorkOrder.production_order_id.label("order_id"),
        WorkOrder.production_batch_id.label("work_batch_id"), SewingAssignment.production_batch_id.label("batch_id"),
        SewingFlow.factory_code.label("factory_code")).select_from(WorkOrder).join(
        SewingAssignment, SewingAssignment.work_order_id == WorkOrder.id).join(
        SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id).where(
        WorkOrder.operation == "sewing", WorkOrder.status.notin_(("cancelled", "rejected")),
        SewingAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES))


def _direct_flow_query():
    from sqlalchemy import select
    # A work order's former primary line is stale once active split assignments
    # exist. Only unsplit work can use this persisted line as factory authority.
    active_split = select(SewingAssignment.id).where(SewingAssignment.work_order_id == WorkOrder.id,
        SewingAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES)).exists()
    return select(WorkOrder.id).select_from(WorkOrder).join(SewingFlow,
        SewingFlow.id == WorkOrder.sewing_flow_id).where(WorkOrder.operation == "sewing",
        WorkOrder.status.notin_(("cancelled", "rejected")), ~active_split)


def _eco_assigned_order_query():
    return _active_assignment_query().with_only_columns(WorkOrder.production_order_id).where(
        _factory_condition(SewingFlow.factory_code, {SewingFactoryCode.ECO_COTTON}))


def sewing_assignment_work_ids(factory_codes: set[SewingFactoryCode], batch_id: int | None = None):
    condition = _factory_condition(SewingFlow.factory_code, factory_codes)
    query = _active_assignment_query().with_only_columns(WorkOrder.id).where(condition)
    direct = _direct_flow_query().where(condition)
    if batch_id is not None:
        query = query.where(
            or_(SewingAssignment.production_batch_id == batch_id, SewingAssignment.production_batch_id.is_(None)),
            or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
        direct = direct.where(or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
    return query.union(direct)


def sewing_assignment_factory(db: Session, work_order_id: int, assignment_id: int) -> SewingFactoryCode:
    factory = db.scalar(_active_assignment_query().with_only_columns(SewingFlow.factory_code).where(
        WorkOrder.id == work_order_id, SewingAssignment.id == assignment_id))
    if factory is None:
        raise HTTPException(400, "Selected sewing assignment does not belong to this active work order")
    return canonical_sewing_factory(factory)


def direct_sewing_factory(db: Session, work_order_id: int) -> SewingFactoryCode | None:
    factory = db.scalar(_direct_flow_query().with_only_columns(SewingFlow.factory_code).where(WorkOrder.id == work_order_id))
    return canonical_sewing_factory(factory) if factory is not None else None


def _eco_record_condition():
    eco = {SewingFactoryCode.ECO_COTTON}
    return or_(_factory_condition(SewingFlow.factory_code, eco),
        and_(SewingRecord.sewing_assignment_id.is_(None), or_(
            _factory_condition(Department.code, eco),
            WorkOrder.id.in_(_direct_flow_query().where(_factory_condition(SewingFlow.factory_code, eco))))))


def is_eco_bso_order(db: Session, order_id: int) -> bool:
    return db.query(ProductionOrder.id).filter(ProductionOrder.id == order_id,
        ProductionOrder.planning_order_id.isnot(None), eco_order_condition()).first() is not None


def _order(db: Session, order_id: int, *, lock: bool = False, include_history: bool = False):
    condition = eco_order_condition()
    if include_history:
        condition = or_(condition, ProductionOrder.id.in_(db.query(EcoAccessoryPlan.production_order_id)))
    query = db.query(ProductionOrder).filter(ProductionOrder.id == order_id,
        ProductionOrder.planning_order_id.isnot(None), condition)
    if lock:
        query = query.with_for_update(of=ProductionOrder).populate_existing()
    order = query.first()
    if not order or not db.get(BrandedPlanningOrder, order.planning_order_id):
        raise HTTPException(404, "ecoAccessories.orderRequired")
    return order


def _sewing_started(db: Session, order_id: int) -> bool:
    return bool(db.query(Bundle.id).filter(Bundle.production_order_id == order_id,
        _factory_condition(Bundle.sewing_factory_code, {SewingFactoryCode.ECO_COTTON}),
        Bundle.status.in_(("sent_to_sewing", "received_sewing"))).first() or db.query(SewingRecord.id)
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .join(Department, Department.id == WorkOrder.department_id)
        .outerjoin(SewingAssignment, SewingAssignment.id == SewingRecord.sewing_assignment_id)
        .outerjoin(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
        .filter(WorkOrder.production_order_id == order_id, _eco_record_condition()).first())


def _editable(db: Session, order) -> None:
    if order.status in {"completed", "finished_storage", "cancelled", "rejected"} or _sewing_started(db, order.id):
        raise HTTPException(409, "ecoAccessories.sewingStarted")


def _plan(db: Session, order_id: int, revision: int | None = None):
    try:
        # Existing handoffs can already hold bundle/work-order locks. Refuse a
        # concurrent plan edit instead of reversing their lock order and waiting.
        plan = db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).with_for_update(nowait=True).populate_existing().first()
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03":
            db.rollback()
            raise HTTPException(409, "ecoAccessories.stale") from error
        raise
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
        _factory_condition(Bundle.sewing_factory_code, {SewingFactoryCode.ECO_COTTON}),
        Bundle.status.in_(("sent_to_sewing", "received_sewing"))).distinct().all()}
    started.update(oid for (oid,) in db.query(WorkOrder.production_order_id).join(SewingRecord,
        SewingRecord.work_order_id == WorkOrder.id).join(Department, Department.id == WorkOrder.department_id)
        .outerjoin(SewingAssignment, SewingAssignment.id == SewingRecord.sewing_assignment_id)
        .outerjoin(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
        .filter(WorkOrder.production_order_id.in_(order_ids), _eco_record_condition()).distinct().all())
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
        BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id).filter(or_(eco_order_condition(),
            ProductionOrder.id.in_(db.query(EcoAccessoryPlan.production_order_id))))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(ProductionOrder.production_no.ilike(like), Model.code.ilike(like), BrandedPlanningOrder.order_no.ilike(like)))
    total = query.count()
    rows = query.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    context = _output_context(db, rows) if rows else None
    return {"items": [_output(db, order, context) for order in rows], "total": total}


def get_plan(db: Session, current, order_id: int) -> EcoAccessoryPlanOut:
    _access(current, *READ)
    return _output(db, _order(db, order_id, include_history=True))


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
    if plan:
        issued_by_item = {r.item_id: sum(a.issued_quantity for a in db.query(EcoAccessoryAllocation).filter_by(requirement_id=r.id).all())
            for r in _requirements(db, plan)}
        requested = {item_id: quantity for item_id, quantity, _ in lines}
        if any(requested.get(item_id, 0) < issued for item_id, issued in issued_by_item.items()):
            raise HTTPException(409, "ecoAccessories.issueExceeded")
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
        remaining = req.quantity - sum(a.issued_quantity for a in db.query(EcoAccessoryAllocation).filter_by(requirement_id=req.id).all())
        item = db.get(Item, req.item_id)
        if not item or not item.is_active or item.unit != req.unit or item.category not in {"accessory", "packaging"}:
            raise HTTPException(409, "ecoAccessories.accessoryRequired")
        for batch in batches:
            from app.models.inventory.eco_inventory_service import quality_passed
            if not quality_passed(batch):
                continue
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
    order = _order(db, order_id, lock=True, include_history=True)
    if _sewing_started(db, order.id):
        raise HTTPException(409, "ecoAccessories.sewingStarted")
    plan = _plan(db, order_id, payload.revision)
    if not plan or plan.status not in {Status.PENDING, Status.APPROVED, Status.ISSUED}:
        raise HTTPException(409, "ecoAccessories.pendingOnly")
    requirements = _requirements(db, plan)
    allocations = db.query(EcoAccessoryAllocation).filter(EcoAccessoryAllocation.requirement_id.in_([r.id for r in requirements])).all()
    batches = {b.id: b for b in db.query(EcoMaterialBatch).filter(EcoMaterialBatch.id.in_([a.batch_id for a in allocations]))
        .order_by(EcoMaterialBatch.id).with_for_update().populate_existing().all()} if allocations else {}
    for allocation in allocations:
        batch = batches[allocation.batch_id]
        if batch.reserved_quantity < allocation.quantity - allocation.issued_quantity:
            raise HTTPException(409, "ecoAccessories.allocationMismatch")
    for allocation in allocations:
        batch = batches[allocation.batch_id]
        set_batch_balance(db, batch, quantity=batch.quantity, reserved_quantity=batch.reserved_quantity - (allocation.quantity - allocation.issued_quantity))
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
    if order.status in {"completed", "finished_storage", "cancelled", "rejected"}:
        raise HTTPException(409, "ecoAccessories.sewingStarted")
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


def eco_accessory_readiness(db: Session, order_id: int) -> dict | None:
    """Shared send/receive/start gate. Never consult Milana's accessory balance.

    Non-BSO Usluga stays on its existing path. Previously sewn orders with no new
    plan retain their historical gate; creating a plan cannot rewrite that work.
    """
    if not is_eco_bso_order(db, order_id):
        return None
    order = _order(db, order_id)
    plan = _plan(db, order_id)
    if not plan and _sewing_started(db, order_id):
        return None
    complete = bool(plan and plan.status in {Status.APPROVED, Status.ISSUED} and _snapshot_matches(plan, order))
    return {"is_complete": complete, "status": plan.status if plan else Status.DRAFT.value,
        "production_order_id": order_id, "sewing_gate_active": True,
        "warning": None if complete else "ecoAccessories.approvalRequired", "summary": {}}


def ensure_eco_accessory_approval(db: Session, order_id: int) -> dict | None:
    plan = eco_accessory_readiness(db, order_id)
    if plan is not None and not plan["is_complete"]:
        raise HTTPException(409, "ecoAccessories.approvalRequired")
    return plan


def accessory_gate_factories(db: Session, order_id: int, batch_id: int | None = None) -> set[SewingFactoryCode]:
    from sqlalchemy import select
    query = select(Bundle.sewing_factory_code).where(Bundle.production_order_id == order_id, Bundle.status != "cancelled")
    if batch_id is not None:
        query = query.where(Bundle.production_batch_id == batch_id)
    assignments = _active_assignment_query().with_only_columns(SewingFlow.factory_code).where(WorkOrder.production_order_id == order_id)
    if batch_id is not None:
        assignments = assignments.where(
            or_(SewingAssignment.production_batch_id == batch_id, SewingAssignment.production_batch_id.is_(None)),
            or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
    direct = _direct_flow_query().with_only_columns(SewingFlow.factory_code).where(WorkOrder.production_order_id == order_id)
    if batch_id is not None:
        direct = direct.where(or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
    factories = {canonical_sewing_factory(code) for code in db.scalars(query.union(assignments, direct))}
    if factories:
        return factories
    query = db.query(Department.code).join(WorkOrder, WorkOrder.department_id == Department.id).filter(
        WorkOrder.production_order_id == order_id, WorkOrder.operation == "sewing", WorkOrder.status.notin_(("cancelled", "rejected")))
    if batch_id is not None:
        query = query.filter(or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
    return {canonical_sewing_factory(code) for (code,) in query.distinct().all()} or {SewingFactoryCode.MILANA}


def sync_eco_accessory_block(db: Session, order_id: int, *, batch_id: int | None = None) -> dict | None:
    plan = eco_accessory_readiness(db, order_id)
    if plan is None:
        return None
    query = db.query(WorkOrder).join(Department, Department.id == WorkOrder.department_id).filter(
        or_(Department.code == "ECO", WorkOrder.id.in_(sewing_assignment_work_ids({SewingFactoryCode.ECO_COTTON}, batch_id))),
        WorkOrder.production_order_id == order_id, WorkOrder.operation == "sewing",
        WorkOrder.status.notin_(("completed", "cancelled", "rejected")))
    if batch_id is not None:
        query = query.filter(or_(WorkOrder.production_batch_id == batch_id, WorkOrder.production_batch_id.is_(None)))
    for work in query.all():
        if (not work.is_blocked and work.block_reason is None) or work.block_reason in {
            "Accessories must be issued before sewing.", "ecoAccessories.approvalRequired",
        }:
            writes.set_sewing_block(db, work, blocked=not plan["is_complete"])
    db.flush()
    return plan
