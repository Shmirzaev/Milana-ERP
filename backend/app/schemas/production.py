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


class ProductionOrderIn(BaseModel):
    production_type: str  # client_order | branded_stock
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    planned_quantity: int = 0
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    destination_warehouse_id: Optional[int] = None
    items: list[ProductionOrderItemIn] = []


class ProductionOrderOut(ORMModel):
    id: int
    production_no: str
    production_type: str
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    status: str
    planned_quantity: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    destination_warehouse_id: Optional[int] = None
    created_at: datetime


class WorkOrderOut(ORMModel):
    id: int
    production_order_id: int
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
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None
    assigned_to: Optional[int] = None
    sewing_flow_id: Optional[int] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    notes: Optional[str] = None


class ProductionOrderDetail(ProductionOrderOut):
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
    fabric_batch_id: Optional[int] = None
    input_quantity: float
    input_unit: str = "meter"
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
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int = 0
    rework_qty: int = 0
    rejected_qty: int = 0
    defect_reason: Optional[str] = None
    line_name: Optional[str] = None
    operator_id: Optional[int] = None
    notes: Optional[str] = None


class PackagingRecordIn(BaseModel):
    work_order_id: int
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
