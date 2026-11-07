"""HTTP adapters for isolated Eco stock and two-sided factory fabric transfers."""
from fastapi import APIRouter, Query, Response

from app.core.deps import CurrentUser, DbSession
from app.libs.dto.inventory.eco_inventory_input import EcoMaterialConsumeIn, EcoMaterialReceiveIn, EcoMaterialBulkReceiveIn, FactoryFabricDispatchIn, FactoryFabricReceiptIn, EcoWarehouseIn, EcoQualityIn
from app.libs.dto.inventory.eco_inventory_output import EcoMaterialBatchOut, EcoMaterialItemOut, EcoMaterialMovementOut, EcoMaterialMutationOut, EcoMaterialOrderOut, FactoryFabricSourceBatchOut, FactoryFabricTransferOut, EcoNamedOptionOut
from app.libs.enums.eco_inventory import EcoMaterialKind, FactoryFabricTransferStatus
from app.models.inventory import eco_inventory_service as stock
from app.models.inventory import factory_fabric_transfers_service as transfers

router = APIRouter(tags=["eco-inventory"])


@router.get("/eco-inventory/suppliers", response_model=list[EcoNamedOptionOut])
def receipt_suppliers(db: DbSession, current: CurrentUser):
    return stock.receipt_options(db, current, suppliers=True)


@router.get("/eco-inventory/warehouses", response_model=list[EcoNamedOptionOut])
def receipt_warehouses(db: DbSession, current: CurrentUser):
    return stock.receipt_options(db, current)


@router.post("/eco-inventory/warehouses", response_model=EcoNamedOptionOut)
def create_warehouse(payload: EcoWarehouseIn, db: DbSession, current: CurrentUser):
    return stock.create_warehouse(db, current, payload)


@router.patch("/eco-inventory/batches/{batch_id}/quality", response_model=EcoMaterialBatchOut)
def quality(batch_id: int, payload: EcoQualityIn, db: DbSession, current: CurrentUser):
    return stock.update_quality(db, current, batch_id, payload)


@router.get("/eco-inventory/orders", response_model=list[EcoMaterialOrderOut])
def list_orders(db: DbSession, current: CurrentUser):
    return stock.list_orders(db, current)


@router.get("/eco-inventory/items", response_model=list[EcoMaterialItemOut])
def list_items(db: DbSession, current: CurrentUser, kind: EcoMaterialKind):
    return stock.list_items(db, current, kind)


@router.get("/eco-inventory/stock", response_model=list[EcoMaterialBatchOut])
def list_stock(db: DbSession, current: CurrentUser, kind: EcoMaterialKind | None = None,
               offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500), q: str = Query("", max_length=200)):
    return stock.list_stock(db, current, kind, offset, limit, q)


@router.get("/eco-inventory/history", response_model=list[EcoMaterialMovementOut])
def list_history(db: DbSession, current: CurrentUser, kind: EcoMaterialKind | None = None,
                 batch_id: int | None = Query(None, gt=0), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    return stock.list_history(db, current, kind, batch_id, offset, limit)


@router.post("/eco-inventory/receive", response_model=EcoMaterialMutationOut)
def receive_stock(payload: EcoMaterialReceiveIn, db: DbSession, current: CurrentUser):
    return stock.receive_stock(db, payload, current)


@router.post("/eco-inventory/receive-bulk", response_model=list[EcoMaterialMutationOut])
def receive_stock_bulk(payload: EcoMaterialBulkReceiveIn, db: DbSession, current: CurrentUser):
    return stock.receive_stock_bulk(db, payload, current)


@router.post("/eco-inventory/consume", response_model=EcoMaterialMutationOut)
def consume_stock(payload: EcoMaterialConsumeIn, db: DbSession, current: CurrentUser):
    return stock.consume_stock(db, payload, current)


@router.get("/factory-fabric-transfers/source-batches", response_model=list[FactoryFabricSourceBatchOut])
def source_batches(db: DbSession, current: CurrentUser, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500),
                   q: str | None = Query(None, max_length=120)):
    return transfers.source_batches(db, current, offset, limit, q)


@router.get("/factory-fabric-transfers", response_model=list[FactoryFabricTransferOut])
def list_transfers(db: DbSession, current: CurrentUser, status: FactoryFabricTransferStatus | None = None,
                   offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    return transfers.list_transfers(db, current, status, offset, limit)


@router.post("/factory-fabric-transfers/dispatch", response_model=FactoryFabricTransferOut)
def dispatch(payload: FactoryFabricDispatchIn, db: DbSession, current: CurrentUser):
    return transfers.dispatch(db, payload, current)


@router.post("/factory-fabric-transfers/{transfer_id}/receive", response_model=FactoryFabricTransferOut)
def receive(transfer_id: int, payload: FactoryFabricReceiptIn, db: DbSession, current: CurrentUser):
    return transfers.receive(db, transfer_id, payload, current)


@router.get("/factory-fabric-transfers/{transfer_id}/excel")
def delivery_excel(transfer_id: int, db: DbSession, current: CurrentUser):
    filename, content = transfers.delivery_excel(db, transfer_id, current)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
