from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, SchemaModel
from app.schemas.inventory import ItemComposition


class ProductionOrderItemIn(SchemaModel):
    model_id: int
    color: str
    size: str
    planned_quantity: int
    printing_required: bool = False


class ProductionOrderItemOut(ORMModel):
    id: int
    production_order_id: int
    model_id: int
    color: str
    size: str
    planned_quantity: int
    completed_quantity: int
    printing_required: bool


class ProductionOrderPrintingAttachment(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None


class ProductionOrderMaterialIn(BaseModel):
    stock_batch_id: int
    estimated_quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)


class ProductionOrderMaterialOut(ORMModel):
    id: int
    production_order_id: int
    stock_batch_id: int
    estimated_quantity: float
    unit: str
    position: int


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


class ProductionOrderIn(SchemaModel):
    production_type: str  # client_order | branded_stock
    planning_order_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    brand_id: Optional[int] = None
    fabric_batch_id: Optional[int] = None
    planned_quantity: int = 0
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    estimated_material_code: Optional[str] = None
    estimated_material_amount: Optional[float] = None
    estimated_material_unit: Optional[str] = None
    materials: list[ProductionOrderMaterialIn] = Field(default_factory=list)
    printing_instructions: Optional[str] = None
    printing_attachments: list[ProductionOrderPrintingAttachment] = Field(default_factory=list)
    destination_warehouse_id: Optional[int] = None
    cutting_department_code: str = "CUT"
    sewing_factory_code: Optional[str] = None
    items: list[ProductionOrderItemIn] = []
    batches: list[ProductionBatchIn] = []


class ProductionOrderOut(ORMModel):
    id: int
    production_no: str
    order_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    production_type: str
    source_type: str = "standard"
    planning_order_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    collection_id: Optional[int] = None
    model_id: int
    brand_id: Optional[int] = None
    fabric_batch_id: Optional[int] = None
    status: str
    planned_quantity: int
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    estimated_material_code: Optional[str] = None
    estimated_material_amount: Optional[float] = None
    estimated_material_unit: Optional[str] = None
    materials: list[ProductionOrderMaterialOut] = Field(default_factory=list)
    printing_instructions: Optional[str] = None
    printing_attachments: Optional[list[ProductionOrderPrintingAttachment]] = Field(default_factory=list)
    estimated_material_composition: list[ItemComposition] = Field(default_factory=list)
    model_image_url: Optional[str] = None
    material_image_url: Optional[str] = None
    destination_warehouse_id: Optional[int] = None
    sewing_factory_code: Optional[str] = None
    service_customer_name: Optional[str] = None
    service_customer_reference: Optional[str] = None
    service_material_description: Optional[str] = None
    service_material_usage_kg: Optional[float] = None
    service_material_notes: Optional[str] = None
    service_handover_recipient: Optional[str] = None
    service_handover_notes: Optional[str] = None
    handed_over_at: Optional[datetime] = None
    handed_over_by: Optional[int] = None
    created_at: datetime
    actual_quantity: Optional[int] = None
    actual_bundle_quantity: Optional[int] = None
    actual_bundle_count: Optional[int] = None
    actual_cut_quantity: Optional[int] = None


class BrandedPlanningOrderIn(SchemaModel):
    ordered_for_type: str = "milana"
    customer_id: Optional[int] = None
    notes: Optional[str] = None


class BrandedPlanningOrderOut(ORMModel):
    id: int
    order_no: str
    ordered_for_type: str
    customer_id: Optional[int] = None
    ordered_for_name: str
    status: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class WorkOrderOut(ORMModel):
    id: int
    sewing_assignment_id: Optional[int] = None
    order_no: Optional[str] = None
    production_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    production_order_id: int
    production_batch_id: Optional[int] = None
    assignment_batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    batch_name: Optional[str] = None
    batch_index: Optional[int] = None
    batch_planned_quantity: Optional[int] = None
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
    assigned_qty: int = 0
    assignable_qty: int = 0
    model_image_url: Optional[str] = None
    material_image_url: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None
    assigned_to: Optional[int] = None
    sewing_flow_id: Optional[int] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    notes: Optional[str] = None


class ProductionOrderDetail(ProductionOrderOut):
    model_code: Optional[str] = None
    model_name: Optional[str] = None
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


class CuttingMaterialUsageIn(BaseModel):
    stock_batch_id: int
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)


class CuttingMaterialUsageOut(ORMModel):
    id: int
    cutting_record_id: int
    stock_batch_id: int
    quantity: float
    unit: str
    position: int


class CuttingRecordIn(BaseModel):
    model_config = {"protected_namespaces": ()}

    work_order_id: int
    production_batch_id: Optional[int] = None
    fabric_batch_id: Optional[int] = None
    model_bom_id: Optional[int] = None
    input_quantity: float
    input_unit: str = "kg"
    cut_pieces: int
    report_piece_count: int = Field(default=0, ge=0)
    passed_pieces: int
    defective_pieces: int = 0
    waste_quantity: float = 0
    waste_unit: str = "kg"
    layer_material_kg: float = Field(default=0, ge=0)
    beika_kg: float = Field(default=0, ge=0)
    material_rolls_used: float = Field(default=0, ge=0)
    operator_id: Optional[int] = None
    layup_operator_name: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None
    materials: list[CuttingMaterialUsageIn] = Field(default_factory=list)
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


class SewingSizeQuantityIn(BaseModel):
    size: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0)


class SewingRecordIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int = 0
    rework_qty: int = 0
    rejected_qty: int = 0
    size_quantities: list[SewingSizeQuantityIn] = Field(default_factory=list)
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
    composition: list[ItemComposition] = Field(default_factory=list)
    required_quantity: float
    available_quantity: float
    shortage: float
    unit: str


class PlanningEstimateMaterial(BaseModel):
    item_id: int
    sku: str
    name: str
    category: str | None = None
    composition: list[ItemComposition] = Field(default_factory=list)
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
