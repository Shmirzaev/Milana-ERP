from datetime import datetime
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.common import ORMModel, SchemaModel


PackageWeight = Annotated[
    float,
    Field(le=9_999_999_999.9999, allow_inf_nan=False),
]


class BundleIn(SchemaModel):
    production_order_id: int
    production_batch_id: Optional[int] = None
    cutting_record_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    size: str
    quantity: int = Field(le=2_147_483_647)
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

    @field_serializer("qr_code_url")
    def current_qr_image_url(self, _value: str | None) -> str:
        # Never advertise a cached PNG containing an old order reference.
        return f"/api/barcode/bundle-image/{self.id}"


class BundleScanLogOut(ORMModel):
    id: int
    bundle_id: int
    scanned_by: Optional[int] = None
    scan_type: str
    from_department_id: Optional[int] = None
    to_department_id: Optional[int] = None
    location: Optional[str] = None
    scanned_at: datetime


class BundleHistoryOut(SchemaModel):
    id: int
    scan_type: str
    scanned_by: Optional[int] = None
    from_department_id: Optional[int] = None
    to_department_id: Optional[int] = None
    scanned_at: datetime


class BundleHistoryPageOut(SchemaModel):
    rows: list[BundleHistoryOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class SewingReceiveOptionOut(SchemaModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_batch_id: int | None = None
    batch_label: str | None = None
    model_id: int
    production_no: str
    order_no: str
    model_code: str | None = None
    model_name: str | None = None
    material_image_url: str | None = None
    bundle_count: int
    quantity: int


class SewingReceiveOptionPageOut(SchemaModel):
    rows: list[SewingReceiveOptionOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class BundleDetail(BundleOut):
    scan_logs: list[BundleScanLogOut] = []


class PackageItemIn(SchemaModel):
    model_id: int
    color: str = Field(max_length=64)
    size: str = Field(max_length=32)
    quantity: int = Field(le=2_147_483_647)


class PackageItemOut(ORMModel):
    id: int
    package_id: int
    model_id: int
    color: str
    size: str
    quantity: int


class PackageBatchAllocationIn(BaseModel):
    production_batch_id: int
    quantity: int = Field(le=2_147_483_647)


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
    weight_kg: Optional[PackageWeight] = None
    warehouse_id: Optional[int] = None
    items: list[PackageItemIn]
    batch_allocations: list[PackageBatchAllocationIn] = []
    override_capacity: bool = False
    notes: Optional[str] = None


class PackageBulkIn(PackageIn):
    count: int = 1
    weight_kg_values: list[Optional[PackageWeight]] = Field(default_factory=list)


class PackageReceiveStorageIn(BaseModel):
    warehouse_id: Optional[int] = None
    storage_cell: Optional[str] = None
    storage_shelf: Optional[str] = None


class PackageBatchReceiveStorageIn(PackageReceiveStorageIn):
    package_ids: list[int]


class PackageReceivingQueueRemoveIn(BaseModel):
    package_ids: list[int]


class PackageReceivingQueueScanIn(BaseModel):
    code: str


class PackageStoragePlacementIn(BaseModel):
    storage_cell: str
    storage_shelf: Optional[str] = "S1"
    allow_mixed_models: bool = False
    enforce_model_guard: bool = False


class PackageBatchStoragePlacementIn(PackageStoragePlacementIn):
    package_ids: list[int]


class PackageEditItemIn(SchemaModel):
    model_id: Optional[int] = None
    color: Optional[str] = Field(default=None, max_length=64)
    size: str = Field(max_length=32)
    quantity: int


class PackageEditPayload(BaseModel):
    color: Optional[str] = None
    package_type: Optional[str] = None
    capacity: Optional[int] = None
    weight_kg: Optional[PackageWeight] = None
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
    manual_receipt_id: Optional[int] = None
    id: int
    package_no: str
    barcode: str
    packaging_department_code: str = "PKG"
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
    model_id: int
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
    print_run_id: Optional[int] = None
    manual_source: Optional[dict] = None
    items: list[PackageItemOut] = []
    batch_allocations: list[PackageBatchAllocationOut] = []
    scan_logs: list[PackageScanLogOut] = []
    legacy_source: Optional[dict] = None


class PackageReceivingQueueItemOut(ORMModel):
    id: int
    package_no: str
    barcode: str
    packaging_department_code: str = "PKG"
    color: str
    package_type: str
    total_quantity: int
    capacity: int
    weight_kg: Optional[float] = None
    status: str
    packed_at: Optional[datetime] = None


class PackageReceivingQueuePageOut(BaseModel):
    rows: list[PackageReceivingQueueItemOut]
    total: int
    offset: int
    limit: int
    has_more: bool


class PackageReceivingQueueRemoveOut(BaseModel):
    count: int
    packages: list[PackageReceivingQueueItemOut]
    total: int
    offset: int
    limit: int
    has_more: bool


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
    model_id: int
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


class FinishedGoodsStockPageOut(ORMModel):
    rows: list[FinishedGoodsStockOut]
    total: int
    page: int
    page_size: int
    has_more: bool
