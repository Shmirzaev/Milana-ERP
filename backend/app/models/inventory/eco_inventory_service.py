"""Eco Cotton stock operations. Public writes own one outer transaction.

`consume_eco_batch` is the participating operation for an approved accessory
issue; its caller verifies allocation ownership and owns commit/idempotency.
"""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.core.dt import as_utc
from app.libs.dto.inventory.eco_inventory_input import EcoMaterialConsumeIn, EcoMaterialReceiveIn
from app.libs.dto.inventory.eco_inventory_output import EcoMaterialBatchOut, EcoMaterialItemOut, EcoMaterialMovementOut, EcoMaterialMutationOut, EcoMaterialOrderOut
from app.libs.enums.eco_inventory import EcoMaterialKind, EcoMaterialMovementKind
from app.models.audit_service import log_action
from app.models.factory_scope_service import require_factory_access
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.schemas import Bundle, Department, Item, ProductionOrder, User, WorkOrder
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.schemas.inventory import eco_inventory_persistence as persistence
from app.models.inventory_access_service import materials_only, require_accessories


def scoped_kind(current: User, kind: EcoMaterialKind | None) -> EcoMaterialKind | None:
    if kind == EcoMaterialKind.ACCESSORY:
        require_accessories(current)
    return EcoMaterialKind.FABRIC if kind is None and materials_only(current) else kind


def require_permission(current: User, permission: str) -> None:
    permissions = user_permissions(current)
    if "*" not in permissions and permission not in permissions:
        raise HTTPException(403, f"Missing permission: {permission}")


def require_eco(current: User, permission: str | None = None) -> None:
    require_factory_access(current, "ECO")
    if permission:
        require_permission(current, permission)


def require_eco_order(db: Session, production_order_id: int) -> ProductionOrder:
    order = db.get(ProductionOrder, production_order_id)
    if not order:
        raise HTTPException(404, "Production order not found")
    assigned = db.query(WorkOrder.id).join(Department, Department.id == WorkOrder.department_id).filter(
        WorkOrder.production_order_id == order.id, WorkOrder.operation == "sewing", Department.code == "ECO",
    ).first()
    routed = db.query(Bundle.id).filter(Bundle.production_order_id == order.id, Bundle.sewing_factory_code == "ECO",
                                        Bundle.status != "cancelled").first()
    if not assigned and not routed:
        raise HTTPException(403, "Production order is not assigned to Eco Cotton sewing")
    return order


def batch_output(db: Session, batch: EcoMaterialBatch, item: Item | None = None) -> EcoMaterialBatchOut:
    item = item if item is not None else db.get(Item, batch.item_id)
    return EcoMaterialBatchOut(id=batch.id, item_id=batch.item_id, item_name=item.name, sku=item.sku,
                               kind=EcoMaterialKind(batch.kind), batch_no=batch.batch_no, color=batch.color,
                               unit=batch.unit, quantity=batch.quantity, reserved_quantity=batch.reserved_quantity,
                               available_quantity=batch.quantity - batch.reserved_quantity, received_at=as_utc(batch.received_at))


def list_items(db: Session, current: User, kind: EcoMaterialKind) -> list[EcoMaterialItemOut]:
    require_eco(current, "eco_inventory.read")
    kind = scoped_kind(current, kind)
    categories = ("fabric", "semi_finished") if kind == EcoMaterialKind.FABRIC else ("accessory", "packaging")
    return [EcoMaterialItemOut(id=item.id, sku=item.sku, name=item.name, unit=item.unit, kind=kind)
            for item in db.query(Item).filter(Item.category.in_(categories), Item.is_active.is_(True)).order_by(Item.name).all()]


def list_orders(db: Session, current: User) -> list[EcoMaterialOrderOut]:
    require_eco(current, "eco_inventory.read")
    assigned = db.query(WorkOrder.production_order_id).join(Department, Department.id == WorkOrder.department_id).filter(
        WorkOrder.operation == "sewing", Department.code == "ECO",
    )
    routed = db.query(Bundle.production_order_id).filter(Bundle.sewing_factory_code == "ECO", Bundle.status != "cancelled")
    orders = db.query(ProductionOrder).filter(
        (ProductionOrder.id.in_(assigned)) | (ProductionOrder.id.in_(routed)), ProductionOrder.source_type != "usluga",
    ).order_by(ProductionOrder.id.desc()).all()
    return [EcoMaterialOrderOut(id=order.id, order_no=order.order_no) for order in orders]


def list_stock(db: Session, current: User, kind: EcoMaterialKind | None = None,
               offset: int = 0, limit: int = 200) -> list[EcoMaterialBatchOut]:
    require_eco(current, "eco_inventory.read")
    kind = scoped_kind(current, kind)
    query = db.query(EcoMaterialBatch, Item).join(Item, Item.id == EcoMaterialBatch.item_id)
    if kind:
        query = query.filter(EcoMaterialBatch.kind == kind.value)
    return [batch_output(db, batch, item) for batch, item in query.order_by(EcoMaterialBatch.id.desc()).offset(offset).limit(limit).all()]


def receive_stock(db: Session, payload: EcoMaterialReceiveIn, current: User) -> EcoMaterialMutationOut:
    require_eco(current, "eco_inventory.receive")
    scoped_kind(current, payload.kind)
    body = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="eco_inventory.receive", key=payload.request_key, payload=body)
    if replay is not None:
        return EcoMaterialMutationOut.model_validate(replay)
    item = db.get(Item, payload.item_id)
    categories = ("fabric", "semi_finished") if payload.kind == EcoMaterialKind.FABRIC else ("accessory", "packaging")
    if not item or not item.is_active or item.category not in categories:
        raise HTTPException(400, "Select an active material of the selected inventory kind")
    batch = persistence.insert_batch(db, item_id=item.id, kind=payload.kind, batch_no=payload.batch_no,
                                      color=payload.color, unit=item.unit, quantity=payload.quantity, created_by=current.id)
    movement = persistence.insert_movement(db, batch_id=batch.id, kind=EcoMaterialMovementKind.RECEIVE,
                                           quantity=payload.quantity, created_by=current.id, notes=payload.notes)
    result = EcoMaterialMutationOut(batch=batch_output(db, batch), movement_id=movement.id)
    log_action(db, current, "receive", "EcoMaterialBatch", batch.id, new_value=body)
    store_idempotent_response(db, scope="eco_inventory.receive", key=payload.request_key,
                              payload=body, response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result


def consume_eco_batch(db: Session, *, batch_id: int, quantity: Decimal, current: User,
                      production_order_id: int | None, reference_type: str | None = None,
                      reference_id: int | None = None, allocated: bool = False,
                      commit: bool = False, notes: str | None = None) -> EcoMaterialMovement:
    """Consume locked stock using a caller-validated allocation, if supplied.

    This function is not an HTTP authorization boundary. The owning public
    operation must verify its permission, idempotency and allocation identity.
    It still enforces selected factory, order assignment and physical balances.
    """
    require_eco(current)
    quantity = Decimal(str(quantity))
    if not quantity.is_finite() or quantity <= 0 or quantity >= Decimal("10000000000") or quantity != quantity.quantize(Decimal("0.0001")):
        raise HTTPException(400, "Quantity must be positive with at most four decimal places")
    if production_order_id:
        require_eco_order(db, production_order_id)
    batch = db.execute(select(EcoMaterialBatch).where(EcoMaterialBatch.id == batch_id)
                       .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Eco Cotton material batch not found")
    if allocated:
        if batch.reserved_quantity < quantity or batch.quantity < quantity:
            raise HTTPException(409, "Allocated Eco Cotton stock is insufficient")
        reserved = batch.reserved_quantity - quantity
    else:
        if batch.quantity - batch.reserved_quantity < quantity:
            raise HTTPException(409, "Available Eco Cotton stock is insufficient")
        reserved = batch.reserved_quantity
    persistence.set_batch_balance(db, batch, quantity=batch.quantity - quantity, reserved_quantity=reserved)
    movement = persistence.insert_movement(db, batch_id=batch.id,
                                           kind=EcoMaterialMovementKind.ISSUE if allocated else EcoMaterialMovementKind.CONSUME,
                                           quantity=quantity, created_by=current.id, production_order_id=production_order_id,
                                           reference_type=reference_type, reference_id=reference_id, notes=notes)
    if commit:
        db.commit()
    return movement


def consume_stock(db: Session, payload: EcoMaterialConsumeIn, current: User) -> EcoMaterialMutationOut:
    require_eco(current, "eco_inventory.consume")
    body = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="eco_inventory.consume", key=payload.request_key, payload=body)
    if replay is not None:
        return EcoMaterialMutationOut.model_validate(replay)
    batch = db.get(EcoMaterialBatch, payload.batch_id)
    if not batch:
        raise HTTPException(404, "Eco Cotton material batch not found")
    if batch.kind == EcoMaterialKind.ACCESSORY.value:
        raise HTTPException(409, "Issue accessories through the approved production accessory plan")
    movement = consume_eco_batch(db, batch_id=payload.batch_id, quantity=payload.quantity, current=current,
                                 production_order_id=payload.production_order_id, notes=payload.notes)
    result = EcoMaterialMutationOut(batch=batch_output(db, batch), movement_id=movement.id)
    log_action(db, current, "consume", "EcoMaterialBatch", batch.id, new_value=body)
    store_idempotent_response(db, scope="eco_inventory.consume", key=payload.request_key,
                              payload=body, response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result


def list_history(db: Session, current: User, kind: EcoMaterialKind | None = None,
                 batch_id: int | None = None, offset: int = 0, limit: int = 100) -> list[EcoMaterialMovementOut]:
    require_eco(current, "eco_inventory.read")
    kind = scoped_kind(current, kind)
    query = db.query(EcoMaterialMovement, EcoMaterialBatch, Item, User, ProductionOrder).join(
        EcoMaterialBatch, EcoMaterialBatch.id == EcoMaterialMovement.batch_id,
    ).join(Item, Item.id == EcoMaterialBatch.item_id).join(User, User.id == EcoMaterialMovement.created_by).outerjoin(
        ProductionOrder, ProductionOrder.id == EcoMaterialMovement.production_order_id,
    )
    if kind:
        query = query.filter(EcoMaterialBatch.kind == kind.value)
    if batch_id:
        query = query.filter(EcoMaterialBatch.id == batch_id)
    return [EcoMaterialMovementOut(id=movement.id, batch_id=batch.id, batch_no=batch.batch_no, item_name=item.name,
                                   unit=batch.unit, kind=EcoMaterialMovementKind(movement.kind), quantity=movement.quantity,
                                   production_order_id=movement.production_order_id, order_no=order.order_no if order else None,
                                   reference_type=movement.reference_type, reference_id=movement.reference_id,
                                   notes=movement.notes, created_at=as_utc(movement.created_at), operator_name=actor.name)
            for movement, batch, item, actor, order in query.order_by(EcoMaterialMovement.id.desc()).offset(offset).limit(limit).all()]
