from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class BundleIn(BaseModel):
    production_order_id: int
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
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    size: str
    quantity: int
    current_department_id: Optional[int] = None
    next_department_id: Optional[int] = None
    status: str
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


class PackageItemIn(BaseModel):
    model_id: int
    color: str
    size: str
    quantity: int


class PackageItemOut(ORMModel):
    id: int
    package_id: int
    model_id: int
    color: str
    size: str
    quantity: int


class PackageIn(BaseModel):
    production_order_id: int
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    package_type: str = "bag"
    capacity: int = 60
    warehouse_id: Optional[int] = None
    items: list[PackageItemIn]
    override_capacity: bool = False
    notes: Optional[str] = None


class PackageOut(ORMModel):
    id: int
    package_no: str
    barcode: str
    qr_code_url: Optional[str] = None
    production_order_id: int
    sales_order_id: Optional[int] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    color: str
    package_type: str
    total_quantity: int
    capacity: int
    warehouse_id: Optional[int] = None
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
    scan_logs: list[PackageScanLogOut] = []


class FinishedGoodsStockOut(ORMModel):
    id: int
    production_order_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    package_id: Optional[int] = None
    model_id: int
    brand_id: Optional[int] = None
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
