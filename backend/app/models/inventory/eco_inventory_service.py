"""Eco Cotton stock operations. Public writes own one outer transaction.

`consume_eco_batch` is the participating operation for an approved accessory
issue; its caller verifies allocation ownership and owns commit/idempotency.
"""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.core.dt import as_utc
from app.libs.dto.inventory.eco_inventory_input import EcoMaterialConsumeIn, EcoMaterialReceiveIn, EcoMaterialReceiveLineIn, EcoMaterialBulkReceiveIn, EcoReceiptDetails, EcoQualityIn, EcoWarehouseIn
from app.libs.dto.inventory.eco_inventory_output import EcoMaterialBatchOut, EcoMaterialItemOut, EcoMaterialMovementOut, EcoMaterialMutationOut, EcoMaterialOrderOut, EcoNamedOptionOut
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.enums.eco_inventory import EcoMaterialKind, EcoMaterialMovementKind
from app.models.audit_service import log_action
from app.models.factory_scope_service import require_factory_access
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.schemas import Department, Item, ProductionOrder, Supplier, User, Warehouse
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
    from app.models.inventory.eco_accessory_service import eco_order_condition
    if not db.query(ProductionOrder.id).filter(ProductionOrder.id == order.id, eco_order_condition()).first():
        raise HTTPException(403, "Production order is not assigned to Eco Cotton sewing")
    return order


def batch_output(db: Session, batch: EcoMaterialBatch, item: Item | None = None) -> EcoMaterialBatchOut:
    item = item if item is not None else db.get(Item, batch.item_id)
    return EcoMaterialBatchOut(id=batch.id, item_id=batch.item_id, item_name=item.name, sku=item.sku,
                               kind=EcoMaterialKind(batch.kind), batch_no=batch.batch_no, color=batch.color,
                               unit=batch.unit, quantity=batch.quantity, reserved_quantity=batch.reserved_quantity,
                               available_quantity=batch.quantity - batch.reserved_quantity if quality_passed(batch) else Decimal(0),
                               received_at=as_utc(batch.received_at), receipt_details=batch.receipt_details or {})


def quality_passed(batch: EcoMaterialBatch) -> bool:
    return (batch.receipt_details or {}).get("qc_status", "passed") == StockBatchQcStatus.PASSED.value


def receipt_options(db: Session, current: User, *, suppliers: bool = False) -> list[EcoNamedOptionOut]:
    require_eco(current, "eco_inventory.read")
    rows = db.query(Supplier).order_by(Supplier.name).all() if suppliers else db.query(Warehouse).join(
        Department, Department.id == Warehouse.department_id).filter(Department.code.in_(("ECO", "ECT", "ECP"))).order_by(Warehouse.name).all()
    return [EcoNamedOptionOut(id=row.id, name=row.name) for row in rows
            if suppliers or not materials_only(current) or row.type != "accessory_storage"]


def create_warehouse(db: Session, current: User, payload: EcoWarehouseIn) -> EcoNamedOptionOut:
    require_eco(current, "eco_inventory.receive")
    scoped_kind(current, payload.kind)
    department = db.query(Department).filter_by(code="ECO").one()
    existing = db.query(Warehouse).filter(Warehouse.department_id == department.id,
        Warehouse.name == payload.name).first()
    if existing:
        return EcoNamedOptionOut(id=existing.id, name=existing.name)
    row = persistence.insert_eco_warehouse(db, name=payload.name, kind=payload.kind, department_id=department.id)
    log_action(db, current, "create", "Warehouse", row.id, new_value={"name": row.name, "factory": "ECO"})
    db.commit()
    return EcoNamedOptionOut(id=row.id, name=row.name)


def update_quality(db: Session, current: User, batch_id: int, payload: EcoQualityIn) -> EcoMaterialBatchOut:
    require_eco(current, "eco_inventory.receive")
    batch = db.execute(select(EcoMaterialBatch).where(EcoMaterialBatch.id == batch_id).with_for_update()).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Eco Cotton material batch not found")
    scoped_kind(current, EcoMaterialKind(batch.kind))
    if batch.reserved_quantity and payload.qc_status != StockBatchQcStatus.PASSED:
        raise HTTPException(409, "Release approved allocations before placing this batch on hold")
    details = dict(batch.receipt_details or {})
    old_status = details.get("qc_status", "passed")
    details["qc_status"] = payload.qc_status.value
    persistence.set_receipt_details(db, batch, details)
    log_action(db, current, "quality", "EcoMaterialBatch", batch.id,
               old_value={"qc_status": old_status}, new_value={"qc_status": payload.qc_status.value})
    db.commit()
    return batch_output(db, batch)


def list_items(db: Session, current: User, kind: EcoMaterialKind) -> list[EcoMaterialItemOut]:
    require_eco(current, "eco_inventory.read")
    kind = scoped_kind(current, kind)
    categories = ("fabric", "semi_finished") if kind == EcoMaterialKind.FABRIC else ("accessory", "packaging")
    return [EcoMaterialItemOut(id=item.id, sku=item.sku, name=item.name, unit=item.unit, kind=kind, category=item.category)
            for item in db.query(Item).filter(Item.category.in_(categories), Item.is_active.is_(True)).order_by(Item.name).all()]


def list_orders(db: Session, current: User) -> list[EcoMaterialOrderOut]:
    require_eco(current, "eco_inventory.read")
    from app.models.inventory.eco_accessory_service import eco_order_condition
    orders = db.query(ProductionOrder).filter(
        eco_order_condition(), ProductionOrder.source_type != "usluga",
    ).order_by(ProductionOrder.id.desc()).all()
    return [EcoMaterialOrderOut(id=order.id, order_no=order.order_no) for order in orders]


def list_stock(db: Session, current: User, kind: EcoMaterialKind | None = None,
               offset: int = 0, limit: int = 200, q: str = "") -> list[EcoMaterialBatchOut]:
    require_eco(current, "eco_inventory.read")
    kind = scoped_kind(current, kind)
    query = db.query(EcoMaterialBatch, Item).join(Item, Item.id == EcoMaterialBatch.item_id)
    if kind:
        query = query.filter(EcoMaterialBatch.kind == kind.value)
    if q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(or_(*(column.ilike(pattern, escape="\\") for column in
            (Item.name, Item.sku, EcoMaterialBatch.batch_no, EcoMaterialBatch.color))))
    return [batch_output(db, batch, item) for batch, item in query.order_by(EcoMaterialBatch.id.desc()).offset(offset).limit(limit).all()]


def receive_stock(db: Session, payload: EcoMaterialReceiveIn, current: User) -> EcoMaterialMutationOut:
    require_eco(current, "eco_inventory.receive")
    scoped_kind(current, payload.kind)
    body = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="eco_inventory.receive", key=payload.request_key, payload=body)
    if replay is not None:
        return EcoMaterialMutationOut.model_validate(replay)
    result = _receive_stock_line(db, payload, current)
    store_idempotent_response(db, scope="eco_inventory.receive", key=payload.request_key,
                              payload=body, response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result


def receive_stock_bulk(db: Session, payload: EcoMaterialBulkReceiveIn, current: User) -> list[EcoMaterialMutationOut]:
    """One receipt table is atomic and retries replay its original complete result."""
    require_eco(current, "eco_inventory.receive")
    for line in payload.lines:
        scoped_kind(current, line.kind)
    body = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="eco_inventory:receive-bulk", key=payload.request_key, payload=body)
    if replay is not None:
        return [EcoMaterialMutationOut.model_validate(row) for row in replay["lines"]]
    # Stable catalog lock order also covers repeated material rows with different lots.
    db.execute(select(Item).where(Item.id.in_(sorted({line.item_id for line in payload.lines})))
               .order_by(Item.id).with_for_update().execution_options(populate_existing=True)).scalars().all()
    results = [_receive_stock_line(db, line, current) for line in payload.lines]
    store_idempotent_response(db, scope="eco_inventory:receive-bulk", key=payload.request_key,
                              payload=body, response={"lines": [row.model_dump(mode="json") for row in results]}, user=current)
    db.commit()
    return results


def _receive_stock_line(db: Session, payload: EcoMaterialReceiveLineIn, current: User) -> EcoMaterialMutationOut:
    """Participates in the public operation's transaction; never commits or retries."""
    body = payload.model_dump(mode="json")
    item = db.execute(select(Item).where(Item.id == payload.item_id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one_or_none()
    categories = ("fabric", "semi_finished") if payload.kind == EcoMaterialKind.FABRIC else ("accessory", "packaging")
    if not item or not item.is_active or item.category not in categories:
        raise HTTPException(400, "Select an active material of the selected inventory kind")
    details = EcoReceiptDetails.model_validate({key: body[key] for key in EcoReceiptDetails.model_fields}).model_dump(mode="json")
    if payload.supplier_id:
        supplier = db.get(Supplier, payload.supplier_id)
        if not supplier:
            raise HTTPException(400, "Supplier not found")
        details["supplier_name"] = supplier.name
    if payload.warehouse_id:
        warehouse = db.query(Warehouse).join(Department, Department.id == Warehouse.department_id).filter(
            Warehouse.id == payload.warehouse_id, Department.code.in_(("ECO", "ECT", "ECP"))).first()
        if not warehouse:
            raise HTTPException(403, "Select an ECO COTTON warehouse")
        if materials_only(current) and warehouse.type == "accessory_storage":
            raise HTTPException(403, "Accessory warehouses are not available to this account")
        details["warehouse_name"] = warehouse.name
    if payload.production_order_id:
        require_eco_order(db, payload.production_order_id)
    from app.models.inventory.stock_service import _validate_item_image_url
    details["image_url"] = _validate_item_image_url(payload.image_url)
    unit = payload.unit or item.unit
    if payload.kind == EcoMaterialKind.ACCESSORY and unit != item.unit:
        raise HTTPException(400, "Accessory receipt unit must match its material catalog unit")
    if payload.roll_weights_kg and unit != "kg":
        raise HTTPException(400, "Individual roll weights require kg")
    batch = persistence.insert_batch(db, item_id=item.id, kind=payload.kind, batch_no=payload.batch_no,
                                      color=payload.color, unit=unit, quantity=payload.quantity, created_by=current.id,
                                      receipt_details=details)
    movement = persistence.insert_movement(db, batch_id=batch.id, kind=EcoMaterialMovementKind.RECEIVE,
                                           quantity=payload.quantity, created_by=current.id, notes=payload.notes,
                                           production_order_id=payload.production_order_id)
    result = EcoMaterialMutationOut(batch=batch_output(db, batch), movement_id=movement.id)
    log_action(db, current, "receive", "EcoMaterialBatch", batch.id, new_value=body)
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
    if not quality_passed(batch):
        raise HTTPException(409, "Material must pass quality inspection before consumption or issue")
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
