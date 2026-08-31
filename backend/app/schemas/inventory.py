from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


class ItemComposition(BaseModel):
    name: str
    percentage: float = Field(ge=0, le=100)


class ItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float = 0
    reorder_level: float = 0
    track_batch: bool = False
    is_active: bool = True
    image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)


class ItemImageIn(BaseModel):
    image_url: Optional[str] = None


class ItemOut(ORMModel):
    id: int
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float
    reorder_level: float
    track_batch: bool
    is_active: bool
    image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)


class WarehouseIn(BaseModel):
    name: str
    type: str
    department_id: Optional[int] = None


class WarehouseOut(ORMModel):
    id: int
    name: str
    type: str
    department_id: Optional[int] = None


class StockBatchIn(BaseModel):
    item_id: int
    batch_no: str
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list)
    processes: Optional[str] = None
    unit: str
    cost_per_unit: float = 0
    image_url: Optional[str] = None
    warehouse_id: int
    qc_status: str = "pending"


class StockBatchUpdate(BaseModel):
    item_id: Optional[int] = None
    batch_no: Optional[str] = None
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: Optional[float] = Field(default=None, ge=0)
    piece_count: Optional[int] = Field(default=None, ge=0)
    processes: Optional[str] = None
    unit: Optional[str] = None
    cost_per_unit: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    received_date: Optional[datetime] = None
    warehouse_id: Optional[int] = None
    qc_status: Optional[str] = None


class StockBatchRollWeightsIn(BaseModel):
    roll_weights_kg: list[float] = Field(min_length=1, max_length=1000)


class AccessoryReturnIn(StockBatchIn):
    production_order_id: int
    return_condition: Optional[str] = "used"


class StockBatchOut(ORMModel):
    id: int
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    item_category: Optional[str] = None
    batch_no: str
    internal_batch_no: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list)
    processes: Optional[str] = None
    unit: str
    cost_per_unit: float
    image_url: Optional[str] = None
    received_date: datetime
    warehouse_id: int
    warehouse_name: Optional[str] = None
    qc_status: str
    reserved_quantity: float = 0
    available_quantity: float = 0
    active_reservations: list[dict] = []


class StockMovementIn(BaseModel):
    movement_type: str
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None


class StockMovementOut(ORMModel):
    id: int
    movement_type: str
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime


class StockQuantityAdjustmentIn(BaseModel):
    quantity: float = Field(ge=0)
    unit: Optional[str] = None


class StockQuantityAdjustmentOut(BaseModel):
    item_id: int
    previous_quantity: float
    quantity: float
    delta: float
    unit: str
    movement_id: Optional[int] = None
    movement_type: Optional[str] = None


class StockLine(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    warehouse_id: int
    quantity: float
    unit: str
    reserved_quantity: float = 0
    available_quantity: float = 0


class MaterialReservationOut(ORMModel):
    id: int
    reservation_no: str
    production_order_id: int
    sales_order_id: Optional[int] = None
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    stock_batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    reserved_quantity: float
    consumed_quantity: float
    released_quantity: float
    unit: str
    status: str
    reservation_type: str
    source: str
    reserved_by: Optional[int] = None
    reserved_at: datetime
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MaterialReservationIn(BaseModel):
    production_order_id: int
    item_id: int
    stock_batch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    reserved_quantity: float = Field(gt=0)
    unit: str
    reservation_type: str = "material"
    notes: Optional[str] = None


class MaterialReservationAutoIn(BaseModel):
    production_order_id: int
    mode: str = "full_remaining"
    reserve_accessories: bool = True
    reserve_materials: bool = True
    reserve_packaging: bool = True


class MaterialReservationConsumeIn(BaseModel):
    quantity: float = Field(gt=0)


class ReservationBatchSuggestion(BaseModel):
    stock_batch_id: int
    batch_no: str
    warehouse_id: int
    received_date: datetime
    current_quantity: float
    reserved_quantity: float
    available_quantity: float
    suggested_quantity: float
    unit: str


class MaterialReservationPlanRow(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)
    category: str
    reservation_type: str
    unit: str
    stock_batch_id: Optional[int] = None
    stock_batch_no: Optional[str] = None
    stock_batch_image_url: Optional[str] = None
    stock_batch_color: Optional[str] = None
    required_quantity: float
    already_reserved_quantity: float
    remaining_to_reserve: float
    current_stock: float
    reserved_stock: float
    available_stock: float
    shortage: float
    suggested_batches: list[ReservationBatchSuggestion] = []
    status: str


class MaterialReservationPlanOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    sales_order_id: Optional[int] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    status: str
    is_complete: bool
    warning: Optional[str] = None
    summary: dict
    rows: list[MaterialReservationPlanRow]


class MaterialReservationStatusOut(BaseModel):
    plan: MaterialReservationPlanOut
    summary: dict
    reservations: list[MaterialReservationOut]


class AccessoryIssuePlanRow(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    required_quantity: float
    issued_quantity: float
    remaining_quantity: float
    available_quantity: float
    shortage: float
    status: str


class AccessoryIssuePlanOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    status: str
    is_complete: bool
    warning: Optional[str] = None
    summary: dict
    rows: list[AccessoryIssuePlanRow]


class AccessoryIssueLineIn(BaseModel):
    item_id: Optional[int] = None
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    manual: bool = False


class AccessoryIssueIn(BaseModel):
    production_order_id: int
    lines: list[AccessoryIssueLineIn]
    notes: Optional[str] = None


class AccessoryIssueLineOut(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    quantity: float
    unit: str


class AccessoryIssueOut(BaseModel):
    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    issued: list[AccessoryIssueLineOut]


class AccessoryIssueSummaryRow(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    issued_quantity: float
    returned_quantity: float = 0
    returnable_quantity: float = 0
    movement_count: int
    first_issued_at: Optional[datetime] = None
    last_issued_at: Optional[datetime] = None


class AccessoryIssueRequestRow(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    required_quantity: float
    issued_quantity: float
    remaining_quantity: float
    available_quantity: float
    shortage: float
    status: str
