from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class ProductionOrderItemIn(BaseModel):
    model_id: int
    color: str
    size: str
    planned_quantity: int


class ProductionOrderItemOut(ORMModel):
    id: int
    production_order_id: int
    model_id: int
    color: str
    size: str
    planned_quantity: int
    completed_quantity: int


class ProductionBatchIn(BaseModel):
    batch_no: str | None = None
    name: str | None = None
    planned_quantity: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    notes: str | None = None


class ProductionBatchOut(ORMModel):
    id: int
    production_order_id: int
    batch_no: str
    batch_index: int
    name: str | None = None
    planned_quantity: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    notes: str | None = None


class ProductionOrderIn(BaseModel):
    production_type: str  # client_order | branded_stock
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    planned_quantity: int = 0
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    estimated_material_code: Optional[str] = None
    estimated_material_amount: Optional[float] = None
    estimated_material_unit: Optional[str] = None
    destination_warehouse_id: Optional[int] = None
    items: list[ProductionOrderItemIn] = []
    batches: list[ProductionBatchIn] = []


class ProductionOrderOut(ORMModel):
    id: int
    production_no: str
    order_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    production_type: str
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    status: str
    planned_quantity: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    estimated_material_code: Optional[str] = None
    estimated_material_amount: Optional[float] = None
    estimated_material_unit: Optional[str] = None
    destination_warehouse_id: Optional[int] = None
    created_at: datetime
    actual_quantity: Optional[int] = None
    actual_bundle_quantity: Optional[int] = None
    actual_bundle_count: Optional[int] = None
    actual_cut_quantity: Optional[int] = None


class WorkOrderOut(ORMModel):
    id: int
    order_no: Optional[str] = None
    production_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    production_order_id: int
    production_batch_id: Optional[int] = None
    department_id: int
    operation: str
    status: str
    planned_input_qty: int
    planned_output_qty: int
    actual_input_qty: int
    actual_output_qty: int
    passed_qty: int
    failed_qty: int
    rework_qty: int
    received_bundle_count: int = 0
    received_bundle_qty: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None
    assigned_to: Optional[int] = None
    sewing_flow_id: Optional[int] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    notes: Optional[str] = None


class ProductionOrderDetail(ProductionOrderOut):
    batches: list[ProductionBatchOut] = []
    items: list[ProductionOrderItemOut] = []
    work_orders: list[WorkOrderOut] = []


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    sewing_flow_id: Optional[int] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    actual_input_qty: Optional[int] = None
    actual_output_qty: Optional[int] = None
    passed_qty: Optional[int] = None
    failed_qty: Optional[int] = None
    rework_qty: Optional[int] = None


class CuttingRecordIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    fabric_batch_id: Optional[int] = None
    input_quantity: float
    input_unit: str = "kg"
    cut_pieces: int
    passed_pieces: int
    defective_pieces: int = 0
    waste_quantity: float = 0
    waste_unit: str = "kg"
    operator_id: Optional[int] = None
    notes: Optional[str] = None
    # Bundle plan: list of {color, size, quantity, count}
    bundles: list[dict] = []


class PrintingRecordIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    input_qty: int
    printed_qty: int
    passed_qty: int
    rejected_qty: int = 0
    defect_reason: Optional[str] = None
    print_type: Optional[str] = None
    operator_id: Optional[int] = None
    notes: Optional[str] = None


class SewingRecordIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int = 0
    rework_qty: int = 0
    rejected_qty: int = 0
    defect_reason: Optional[str] = None
    line_name: Optional[str] = None
    sewing_assignment_id: Optional[int] = None
    operator_id: Optional[int] = None
    notes: Optional[str] = None


class PackagingRecordIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    input_qty: int
    packed_qty: int
    damaged_qty: int = 0
    packaging_material_used: Optional[str] = None
    operator_id: Optional[int] = None
    notes: Optional[str] = None


class QualityCheckIn(BaseModel):
    work_order_id: int
    department_id: Optional[int] = None
    checked_qty: int
    passed_qty: int
    failed_qty: int
    defect_type: Optional[str] = None
    defect_reason: Optional[str] = None
    severity: str = "low"


class QualityCheckOut(ORMModel):
    id: int
    work_order_id: int
    department_id: Optional[int] = None
    checked_qty: int
    passed_qty: int
    failed_qty: int
    defect_type: Optional[str] = None
    defect_reason: Optional[str] = None
    severity: str
    checked_at: Optional[datetime] = None


class MaterialRequirement(BaseModel):
    item_id: int
    sku: str
    name: str
    required_quantity: float
    available_quantity: float
    shortage: float
    unit: str


class PlanningEstimateMaterial(BaseModel):
    item_id: int
    sku: str
    name: str
    category: str | None = None
    required_quantity: float
    available_quantity: float
    shortage: float
    unit: str
    unit_cost: float
    estimated_cost: float


class PlanningEstimateOut(BaseModel):
    sales_order_id: int
    status: str
    estimated_material_cost: float
    estimated_labor_cost: float = 0
    estimated_electricity_cost: float = 0
    estimated_other_expenses: float = 0
    estimated_net_cost: float
    suggested_price_15: float
    suggested_price_20: float
    estimated_sales_value: float
    estimated_lead_time_minutes: int
    estimated_lead_time_hours: float
    total_quantity: int
    materials: list[PlanningEstimateMaterial]


class PlanningEstimateSubmitIn(BaseModel):
    estimated_material_cost: float | None = None
    estimated_labor_cost: float | None = None
    estimated_electricity_cost: float | None = None
    estimated_other_expenses: float | None = None
    estimated_lead_time_minutes: int | None = None
    estimate_comment: str | None = None
    planned_deadline: datetime | None = None
