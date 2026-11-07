from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.libs.enums.eco_inventory import EcoMaterialKind, EcoMaterialMovementKind, FactoryFabricTransferStatus
from app.libs.dto.inventory.eco_inventory_input import EcoReceiptDetails


class EcoReceiptDetailsOut(EcoReceiptDetails):
    supplier_name: str | None = None
    warehouse_name: str | None = None


class EcoNamedOptionOut(BaseModel):
    id: int
    name: str


class EcoMaterialItemOut(BaseModel):
    id: int
    sku: str
    name: str
    unit: str
    kind: EcoMaterialKind


class EcoMaterialOrderOut(BaseModel):
    id: int
    order_no: str


class EcoMaterialBatchOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    sku: str
    kind: EcoMaterialKind
    batch_no: str
    color: str | None
    unit: str
    quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal
    received_at: datetime
    receipt_details: EcoReceiptDetailsOut = EcoReceiptDetailsOut()


class EcoMaterialMovementOut(BaseModel):
    id: int
    batch_id: int
    batch_no: str
    item_name: str
    unit: str
    kind: EcoMaterialMovementKind
    quantity: Decimal
    production_order_id: int | None
    order_no: str | None
    reference_type: str | None
    reference_id: int | None
    notes: str | None
    created_at: datetime
    operator_name: str


class FactoryFabricTransferLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_batch_id: int
    item_id: int
    item_name: str
    batch_no: str
    color: str | None
    unit: str
    quantity: Decimal
    received_quantity: Decimal


class FactoryFabricTransferOut(BaseModel):
    id: int
    number: str
    status: FactoryFabricTransferStatus
    dispatched_at: datetime
    operator_name: str
    notes: str | None
    lines: list[FactoryFabricTransferLineOut]


class FactoryFabricSourceBatchOut(BaseModel):
    id: int
    item_name: str
    batch_no: str
    color: str | None
    unit: str
    quantity: Decimal
    available_quantity: Decimal


class EcoMaterialMutationOut(BaseModel):
    batch: EcoMaterialBatchOut
    movement_id: int
