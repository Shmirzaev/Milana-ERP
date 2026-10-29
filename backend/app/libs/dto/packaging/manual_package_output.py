"""Concrete create and recovery responses for manual Packaging."""
from pydantic import BaseModel
from app.libs.enums.packaging import ManualRecoveryStatus


class ManualPackageItemOut(BaseModel):
    model_id: int
    color: str
    size: str
    quantity: int


class ManualBatchAllocationOut(BaseModel):
    production_batch_id: int
    quantity: int


class ManualPackOut(BaseModel):
    id: int
    package_no: str
    barcode: str
    model_id: int
    color: str
    production_order_id: None = None
    production_batch_id: None = None
    manual_receipt_id: int
    legacy_receipt_id: None = None
    batch_allocations: list[ManualBatchAllocationOut]
    quantity: int
    weight_kg: float
    items: list[ManualPackageItemOut]


class ManualPrintRunOut(BaseModel):
    id: int
    run_no: str
    code: str
    created_at: str
    received_at: str | None
    manual_receipt: bool
    count: int
    quantity: int
    package_ids: list[int]
    packages: list[ManualPackOut]


class ManualPackageCreateOut(BaseModel):
    receipt_no: str
    print_run: ManualPrintRunOut


class ManualPackageRecoveryOut(BaseModel):
    status: ManualRecoveryStatus
    result: ManualPackageCreateOut | None = None
