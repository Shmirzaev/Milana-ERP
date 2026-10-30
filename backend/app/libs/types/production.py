"""Typed internal contracts used by production operation persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Required, TypedDict
from app.libs.enums.production import (
    ProductionSourceType,
    ProductionType,
    SewingOutputAssignmentTransitionStatus,
    WorkOrderStatus,
)


@dataclass(frozen=True)
class ProductionOrderCreateValues:
    production_no: str
    production_type: ProductionType
    source_type: ProductionSourceType
    model_id: int
    brand_id: int | None
    fabric_batch_id: int | None
    sales_order_id: int | None
    planning_order_id: int | None
    collection_id: int | None
    planned_quantity: int
    start_date: datetime | None
    deadline: datetime | None
    estimated_material_code: str | None
    estimated_material_amount: float | None
    estimated_material_unit: str | None
    printing_instructions: str | None
    printing_attachments: list[ProductionOrderPrintingAttachmentValues]
    destination_warehouse_id: int | None
    service_customer_name: str | None
    service_customer_reference: str | None
    service_material_description: str | None
    service_material_usage_kg: float | None
    service_material_notes: str | None
    created_by: int | None


@dataclass(frozen=True)
class ProductionOrderMaterialCreateValues:
    stock_batch_id: int
    estimated_quantity: float
    unit: str
    position: int


@dataclass(frozen=True)
class ProductionOrderItemCreateValues:
    model_id: int
    color: str
    size: str
    planned_quantity: int
    printing_required: bool


@dataclass(frozen=True)
class ProductionBatchCreateValues:
    batch_no: str
    batch_index: int
    name: str
    planned_quantity: int
    start_date: datetime | None
    deadline: datetime | None
    notes: str | None


@dataclass(frozen=True)
class WorkOrderCreateValues:
    department_id: int
    operation: str
    status: WorkOrderStatus
    planned_input_qty: int
    planned_output_qty: int
    deadline: datetime | None


@dataclass(frozen=True)
class WorkOrderInitialState:
    work_order_id: int
    status: WorkOrderStatus
    start_time: datetime | None
    set_start_time: bool


class SewingSizeQuantity(TypedDict):
    size: str
    quantity: int


class ProductionOrderPrintingAttachmentValues(TypedDict, total=False):
    file_url: Required[str]
    file_name: str | None
    content_type: str | None


class ProductionOrderItemInputValues(TypedDict, total=False):
    model_id: int
    color: str
    size: str
    planned_quantity: int
    printing_required: bool


class ProductionBatchInputValues(TypedDict, total=False):
    planned_quantity: int | str | float | bool
    name: str | None
    start_date: datetime | None
    deadline: datetime | None
    notes: str | None


@dataclass(frozen=True)
class SewingOutputRecordValues:
    work_order_id: int
    production_batch_id: int | None
    sewing_assignment_id: int | None
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int
    rework_qty: int
    rejected_qty: int
    size_quantities: list[SewingSizeQuantity]
    defect_reason: str | None
    line_name: str | None
    operator_id: int
    notes: str | None


@dataclass(frozen=True)
class SewingOutputAccounting:
    assignment_applied_qty: int
    actual_input_qty: int
    actual_output_qty: int
    passed_qty: int
    failed_qty: int
    rework_qty: int
    assignment_quantity: int | None = None
    assignment_completed_qty: int | None = None
    assignment_status: SewingOutputAssignmentTransitionStatus | None = None
    assignment_actual_start: datetime | None = None
    assignment_actual_end: datetime | None = None
