"""Milana -> Eco Cotton stock ownership transfer, separate from roll custody.

Dispatch removes source stock and keeps its snapshot in transit. Partial receipt
creates Eco stock only for that receipt's quantity. Every write is atomic and
actor/factory-scoped idempotent; transfer/source locks serialize competing writes.
"""
from decimal import Decimal
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, lazyload

from app.libs.dto.inventory.eco_inventory_input import FactoryFabricDispatchIn, FactoryFabricReceiptIn
from app.libs.dto.inventory.eco_inventory_output import FactoryFabricSourceBatchOut, FactoryFabricTransferLineOut, FactoryFabricTransferOut
from app.libs.enums.eco_inventory import EcoMaterialKind, EcoMaterialMovementKind, FactoryFabricTransferStatus, EcoReceiptSource
from app.libs.enums.inventory import StockMovementType, StockBatchQcStatus
from app.models.audit_service import log_action
from app.models.factory_scope_service import require_factory_access, selected_factory_code
from app.core.dt import as_utc
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.inventory.eco_inventory_service import require_permission
from app.models.inventory_service import available_reservation_item_capacity, reserved_stock_for_batch
from app.schemas import Department, EcoFabricRoll, Item, ProductionOrder, ProductionOrderMaterial, StockBatch, User, Warehouse
from app.schemas.inventory.eco_inventory import FactoryFabricTransfer, FactoryFabricTransferLine
from app.schemas.inventory import eco_inventory_persistence as persistence
from app.schemas.inventory import stock_movement_persistence


def require_transfer_access(current: User, permission: str) -> None:
    if selected_factory_code(current) not in ("MIL", "ECO"):
        raise HTTPException(403, "Factory transfers are available only to Milana and Eco Cotton")
    require_permission(current, permission)


def transfer_output(db: Session, transfer: FactoryFabricTransfer) -> FactoryFabricTransferOut:
    actor = db.get(User, transfer.dispatched_by)
    return FactoryFabricTransferOut(id=transfer.id, number=f"MEC-{transfer.id:06d}",
                                     status=FactoryFabricTransferStatus(transfer.status), dispatched_at=as_utc(transfer.dispatched_at),
                                     operator_name=actor.name, notes=transfer.notes,
                                     lines=[FactoryFabricTransferLineOut.model_validate(line) for line in db.query(FactoryFabricTransferLine)
                                            .filter_by(transfer_id=transfer.id).order_by(FactoryFabricTransferLine.id).all()])


def list_transfers(db: Session, current: User, status: FactoryFabricTransferStatus | None = None,
                   offset: int = 0, limit: int = 100) -> list[FactoryFabricTransferOut]:
    require_transfer_access(current, "factory_fabric_transfers.read")
    query = db.query(FactoryFabricTransfer)
    if status:
        query = query.filter(FactoryFabricTransfer.status == status.value)
    return [transfer_output(db, transfer) for transfer in query.order_by(FactoryFabricTransfer.id.desc()).offset(offset).limit(limit).all()]


def _source_is_milana(db: Session, batch: StockBatch) -> bool:
    warehouse = db.get(Warehouse, batch.warehouse_id)
    if not warehouse or warehouse.type != "fabric_storage":
        return False
    if warehouse.department_id:
        department = db.get(Department, warehouse.department_id)
        if not department or department.code in ("ECO", "ECT", "ECP", "BST", "BPK"):
            return False
    return True


def _customer_owned(db: Session, batch_id: int) -> bool:
    return bool(db.query(ProductionOrder.id).outerjoin(ProductionOrderMaterial,
                ProductionOrderMaterial.production_order_id == ProductionOrder.id).filter(
                    ProductionOrder.source_type == "usluga",
                    or_(ProductionOrder.fabric_batch_id == batch_id, ProductionOrderMaterial.stock_batch_id == batch_id),
                ).first())


def source_batches(db: Session, current: User, offset: int = 0, limit: int = 200, q: str | None = None) -> list[FactoryFabricSourceBatchOut]:
    require_factory_access(current, "MIL")
    require_permission(current, "factory_fabric_transfers.dispatch")
    result = []
    customer_owned = select(ProductionOrder.id).outerjoin(ProductionOrderMaterial,
        ProductionOrderMaterial.production_order_id == ProductionOrder.id).where(
            ProductionOrder.source_type == "usluga",
            or_(ProductionOrder.fabric_batch_id == StockBatch.id, ProductionOrderMaterial.stock_batch_id == StockBatch.id),
        ).correlate(StockBatch).exists()
    outstanding_custody = select(EcoFabricRoll.id).where(
        EcoFabricRoll.batch_id == StockBatch.id, EcoFabricRoll.returned_at.is_(None),
    ).correlate(StockBatch).exists()
    query = db.query(StockBatch, Item).options(lazyload(StockBatch.item)).join(
        Item, Item.id == StockBatch.item_id,
    ).join(Warehouse, Warehouse.id == StockBatch.warehouse_id).outerjoin(
        Department, Department.id == Warehouse.department_id,
    ).filter(
        StockBatch.archived_at.is_(None), StockBatch.quantity > 0, Item.category.in_(("fabric", "semi_finished")),
        StockBatch.qc_status == StockBatchQcStatus.PASSED.value,
        Warehouse.type == "fabric_storage",
        or_(Warehouse.department_id.is_(None), Department.code.notin_(("ECO", "ECT", "ECP", "BST", "BPK"))),
        ~customer_owned, ~outstanding_custody,
    )
    if q and q.strip():
        query = query.filter(or_(Item.name.icontains(q.strip(), autoescape=True), StockBatch.batch_no.icontains(q.strip(), autoescape=True),
                                 StockBatch.color.icontains(q.strip(), autoescape=True)))
    batches = query.order_by(StockBatch.id.desc()).offset(offset).limit(limit).all()
    for batch, item in batches:
        available = min(Decimal(batch.quantity) - Decimal(str(reserved_stock_for_batch(db, batch.id))),
                        Decimal(str(available_reservation_item_capacity(db, batch.item_id, batch.warehouse_id))).quantize(Decimal("0.0001")))
        result.append(FactoryFabricSourceBatchOut(id=batch.id, item_name=item.name, batch_no=batch.batch_no,
                                                  color=batch.color, unit=batch.unit, quantity=batch.quantity,
                                                  available_quantity=max(Decimal(0), available)))
    return result


def dispatch(db: Session, payload: FactoryFabricDispatchIn, current: User) -> FactoryFabricTransferOut:
    require_factory_access(current, "MIL")
    require_permission(current, "factory_fabric_transfers.dispatch")
    body = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="factory_fabric_transfers.dispatch", key=payload.request_key, payload=body)
    if replay is not None:
        return FactoryFabricTransferOut.model_validate(replay)
    # Lock all batches, then items in stable order, matching legacy batch-before-item order.
    source_ids = sorted(line.source_batch_id for line in payload.lines)
    batches = db.execute(select(StockBatch).options(lazyload("*")).where(StockBatch.id.in_(source_ids))
                         .order_by(StockBatch.id).with_for_update(of=StockBatch)
                         .execution_options(populate_existing=True)).scalars().all()
    if len(batches) != len(source_ids):
        raise HTTPException(404, "Source stock batch not found")
    item_ids = sorted({batch.item_id for batch in batches})
    items = {item.id: item for item in db.execute(select(Item).where(Item.id.in_(item_ids)).order_by(Item.id)
                                                  .with_for_update(of=Item, key_share=True)).scalars().all()}
    quantities = {line.source_batch_id: line.quantity for line in payload.lines}
    transfer = persistence.insert_transfer(db, created_by=current.id, notes=payload.notes)
    for batch in batches:
        item = items[batch.item_id]
        if batch.archived_at or item.category not in ("fabric", "semi_finished") or not _source_is_milana(db, batch):
            raise HTTPException(409, "Select active Milana fabric-storage batches")
        if batch.qc_status != StockBatchQcStatus.PASSED.value:
            raise HTTPException(409, "Fabric must pass quality inspection before dispatch to ECO COTTON")
        if _customer_owned(db, batch.id):
            raise HTTPException(409, "Customer-owned Usluga fabric cannot be transferred into Eco Cotton stock")
        if db.query(EcoFabricRoll.id).filter_by(batch_id=batch.id, returned_at=None).first():
            raise HTTPException(409, "Return outstanding fabric through the existing Eco custody register first")
        quantity = quantities[batch.id]
        available = min(Decimal(batch.quantity) - Decimal(str(reserved_stock_for_batch(db, batch.id))),
                        Decimal(str(available_reservation_item_capacity(db, batch.item_id, batch.warehouse_id))).quantize(Decimal("0.0001")))
        if quantity > available:
            raise HTTPException(409, f"Transfer exceeds available stock for batch {batch.batch_no}")
        persistence.insert_transfer_line(db, transfer_id=transfer.id, source_batch_id=batch.id, item_id=item.id,
                                          item_name=item.name, batch_no=batch.batch_no, color=batch.color,
                                          unit=batch.unit, quantity=quantity, receipt_details={
                                              "source": EcoReceiptSource.OTHER.value, "unit": batch.unit, "qc_status": StockBatchQcStatus.PASSED.value,
                                              "cost_per_unit": str(batch.cost_per_unit or 0), "old_code": batch.old_code,
                                              "color_code": batch.color_code, "color_status": batch.color_status,
                                              "width": str(batch.width) if batch.width else None,
                                              "gsm": str(batch.gsm) if batch.gsm else None,
                                              "processes": batch.processes, "image_url": batch.image_url,
                                          })
        stock_movement_persistence.set_batch_quantity(db, batch, Decimal(batch.quantity) - quantity)
        stock_movement_persistence.insert_stock_movement(db, movement_type=StockMovementType.ISSUE,
             item_id=item.id, batch_id=batch.id, from_warehouse_id=batch.warehouse_id, to_warehouse_id=None,
             quantity=quantity, unit=batch.unit, reference_type="FactoryFabricTransfer", reference_id=transfer.id, created_by=current.id)
    result = transfer_output(db, transfer)
    log_action(db, current, "dispatch", "FactoryFabricTransfer", transfer.id, new_value=body)
    store_idempotent_response(db, scope="factory_fabric_transfers.dispatch", key=payload.request_key,
                              payload=body, response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result


def receive(db: Session, transfer_id: int, payload: FactoryFabricReceiptIn, current: User) -> FactoryFabricTransferOut:
    require_factory_access(current, "ECO")
    require_permission(current, "factory_fabric_transfers.receive")
    body = payload.model_dump(mode="json")
    scope = f"factory_fabric_transfers.receive:{transfer_id}"
    replay = replay_idempotent_response(db, scope=scope, key=payload.request_key, payload=body)
    if replay is not None:
        return FactoryFabricTransferOut.model_validate(replay)
    transfer = db.execute(select(FactoryFabricTransfer).where(FactoryFabricTransfer.id == transfer_id)
                          .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not transfer:
        raise HTTPException(404, "Fabric transfer not found")
    lines = db.query(FactoryFabricTransferLine).filter_by(transfer_id=transfer_id).order_by(FactoryFabricTransferLine.id).all()
    by_id = {line.id: line for line in lines}
    for receipt in payload.lines:
        line = by_id.get(receipt.line_id)
        if not line:
            raise HTTPException(400, "Receipt line does not belong to this fabric transfer")
        if receipt.quantity > line.quantity - line.received_quantity:
            raise HTTPException(409, "Receipt exceeds outstanding transfer quantity")
    for receipt in payload.lines:
        line = by_id[receipt.line_id]
        batch = persistence.insert_batch(db, item_id=line.item_id, kind=EcoMaterialKind.FABRIC,
             batch_no=line.batch_no, color=line.color, unit=line.unit, quantity=receipt.quantity,
             created_by=current.id, source_stock_batch_id=line.source_batch_id,
             receipt_details={**(line.receipt_details or {}), "document_no": f"MEC-{transfer.id:06d}"})
        persistence.insert_movement(db, batch_id=batch.id, kind=EcoMaterialMovementKind.TRANSFER_RECEIPT,
             quantity=receipt.quantity, created_by=current.id, reference_type="FactoryFabricTransfer",
             reference_id=transfer.id, notes=payload.notes)
        persistence.set_transfer_received(db, line, line.received_quantity + receipt.quantity)
    status = FactoryFabricTransferStatus.RECEIVED if all(line.received_quantity == line.quantity for line in lines) else FactoryFabricTransferStatus.PARTIALLY_RECEIVED
    persistence.set_transfer_status(db, transfer, status)
    db.flush()
    result = transfer_output(db, transfer)
    log_action(db, current, "receive", "FactoryFabricTransfer", transfer.id, new_value=body)
    store_idempotent_response(db, scope=scope, key=payload.request_key, payload=body,
                              response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result


def delivery_excel(db: Session, transfer_id: int, current: User) -> tuple[str, bytes]:
    require_transfer_access(current, "factory_fabric_transfers.read")
    transfer = db.get(FactoryFabricTransfer, transfer_id)
    if not transfer:
        raise HTTPException(404, "Fabric transfer not found")
    record = transfer_output(db, transfer)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Delivery"
    # Explicit string cells protect business names that begin with =,+,-,@.
    def append(values):
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    append(["Fabric delivery / Передача ткани / Mato topshirish", record.number])
    append(["From / От / Kimdan", "Milana", "To / Кому / Kimga", "Eco Cotton"])
    append(["Dispatched / Отправлено / Yuborilgan", record.dispatched_at.isoformat(), record.operator_name])
    append(["Notes / Примечание / Izoh", record.notes or ""])
    append(["Fabric / Ткань / Mato", "Batch / Партия / Partiya", "Color / Цвет / Rang", "Unit / Ед. / Birlik", "Sent / Отправлено / Yuborildi", "Received / Принято / Qabul qilindi", "Outstanding / В пути / Yo'lda"])
    for line in record.lines:
        append([line.item_name, line.batch_no, line.color or "", line.unit, float(line.quantity), float(line.received_quantity), float(line.quantity - line.received_quantity)])
    append(["Driver signature / Подпись водителя / Haydovchi imzosi", "", "Receiver / Получатель / Qabul qiluvchi", ""])
    for row in (1, 5):
        for cell in sheet[row]:
            cell.font = Font(bold=True)
    for name, width in {"A": 42, "B": 26, "C": 26, "D": 24, "E": 24, "F": 26, "G": 30}.items():
        sheet.column_dimensions[name].width = width
    sheet.freeze_panes = "A6"
    sheet.print_options.horizontalCentered = True
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    buffer = BytesIO()
    workbook.save(buffer)
    return f"{record.number}.xlsx", buffer.getvalue()
