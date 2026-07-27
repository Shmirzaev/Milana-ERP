from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, SchemaModel


class BundleIn(SchemaModel):
    production_order_id: int
    production_batch_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    size: str
    quantity: int
    notes: Optional[str] = None


class BundleOut(ORMModel):
    id: int
    bundle_no: str
    barcode: str
    qr_code_url: Optional[str] = None
    production_order_id: int
    production_no: Optional[str] = None
    order_no: Optional[str] = None
    production_batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    batch_name: Optional[str] = None
    batch_index: Optional[int] = None
    batch_label: Optional[str] = None
    tracking_passport_no: Optional[str] = None
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    model_code: Optional[str] = None
    color: str
    size: str
    quantity: int
    current_department_id: Optional[int] = None
    next_department_id: Optional[int] = None
    sewing_factory_code: Optional[str] = None
    status: str
    created_by: Optional[int] = None
    created_at: datetime
    notes: Optional[str] = None


class BundleScanLogOut(ORMModel):
    id: int
    bundle_id: int
    scanned_by: Optional[int] = None
    scan_type: str
    from_department_id: Optional[int] = None
    to_department_id: Optional[int] = None
    location: Optional[str] = None
    scanned_at: datetime


class BundleDetail(BundleOut):
    scan_logs: list[BundleScanLogOut] = []


class PackageItemIn(SchemaModel):
    model_id: int
    color: str
    size: str
    quantity: int


class PackageItemOut(ORMModel):
    id: int
    package_id: int
    model_id: Optional[int] = None
    color: str
    size: str
    quantity: int


class PackageBatchAllocationIn(BaseModel):
    production_batch_id: int
    quantity: int


class PackageBatchAllocationOut(ORMModel):
    id: int
    package_id: int
    production_batch_id: int
    quantity: int


class PackageIn(SchemaModel):
    production_order_id: int
    production_batch_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    package_type: str = "bag"
    capacity: int = 60
    weight_kg: Optional[float] = None
    warehouse_id: Optional[int] = None
    items: list[PackageItemIn]
    batch_allocations: list[PackageBatchAllocationIn] = []
    override_capacity: bool = False
    notes: Optional[str] = None


class PackageBulkIn(PackageIn):
    count: int = 1
    weight_kg_values: list[Optional[float]] = Field(default_factory=list)


class PackageReceiveStorageIn(BaseModel):
    warehouse_id: Optional[int] = None
    storage_cell: Optional[str] = None
    storage_shelf: Optional[str] = None


class PackageBatchReceiveStorageIn(PackageReceiveStorageIn):
    package_ids: list[int]


class PackageStoragePlacementIn(BaseModel):
    storage_cell: str
    storage_shelf: Optional[str] = "S1"


class PackageBatchStoragePlacementIn(PackageStoragePlacementIn):
    package_ids: list[int]


class PackageEditItemIn(SchemaModel):
    model_id: Optional[int] = None
    color: Optional[str] = None
    size: str
    quantity: int


class PackageEditPayload(BaseModel):
    color: Optional[str] = None
    package_type: Optional[str] = None
    capacity: Optional[int] = None
    weight_kg: Optional[float] = None
    warehouse_id: Optional[int] = None
    storage_cell: Optional[str] = None
    storage_shelf: Optional[str] = None
    items: Optional[list[PackageEditItemIn]] = None
    batch_allocations: Optional[list[PackageBatchAllocationIn]] = None
    notes: Optional[str] = None


class PackageChangeRequestIn(BaseModel):
    request_type: Literal["edit", "delete"]
    payload: Optional[PackageEditPayload] = None
    reason: Optional[str] = None


class PackageChangeDecisionIn(BaseModel):
    notes: Optional[str] = None


class PackageOut(ORMModel):
    id: int
    package_no: str
    barcode: str
    qr_code_url: Optional[str] = None
    production_order_id: Optional[int] = None
    legacy_receipt_id: Optional[int] = None
    production_no: Optional[str] = None
    order_no: Optional[str] = None
    production_batch_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    sales_order_no: Optional[str] = None
    customer_name: Optional[str] = None
    order_type: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: Optional[int] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    model_image_url: Optional[str] = None
    color: str
    package_type: str
    total_quantity: int
    capacity: int
    weight_kg: Optional[float] = None
    warehouse_id: Optional[int] = None
    storage_cell: Optional[str] = None
    storage_shelf: Optional[str] = None
    storage_placed_at: Optional[datetime] = None
    status: str
    packed_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    notes: Optional[str] = None


class PackageScanLogOut(ORMModel):
    id: int
    package_id: int
    scanned_by: Optional[int] = None
    scan_type: str
    location: Optional[str] = None
    scanned_at: datetime


class PackageDetail(PackageOut):
    items: list[PackageItemOut] = []
    batch_allocations: list[PackageBatchAllocationOut] = []
    scan_logs: list[PackageScanLogOut] = []


class PackageChangeRequestOut(ORMModel):
    id: int
    package_id: int
    package_no: str
    request_type: str
    status: str
    before_json: Optional[dict] = None
    payload_json: Optional[dict] = None
    reason: Optional[str] = None
    requested_by: Optional[int] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    decision_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FinishedGoodsStockOut(ORMModel):
    id: int
    production_order_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    package_id: Optional[int] = None
    model_id: Optional[int] = None
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: int
    available_qty: int
    reserved_qty: int
    sold_qty: int
    cost_per_piece: float
    selling_price: float
    warehouse_id: Optional[int] = None
    status: str
