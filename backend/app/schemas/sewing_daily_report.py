from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel, SchemaModel


class SewingDailyReportCreate(BaseModel):
    report_date: date
    sewing_flow_id: int
    work_order_id: Optional[int] = None
    sewing_assignment_id: Optional[int] = None
    manual_model_no: Optional[str] = Field(default=None, max_length=64)
    manual_variant_no: Optional[str] = Field(default=None, max_length=64)
    kroy_no: Optional[str] = Field(default=None, max_length=64)
    sewn_qty: int = Field(ge=0)
    section_quantities: Optional[list[int]] = Field(default=None, min_length=3, max_length=3)
    section_no: Optional[int] = Field(default=None, ge=1, le=20)
    section_name: Optional[str] = Field(default=None, max_length=64)
    top_qty: Optional[int] = Field(default=None, ge=0)
    bottom_qty: Optional[int] = Field(default=None, ge=0)
    defective_qty: int = Field(default=0, ge=0)
    defect_reason: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_quantities(self):
        self.manual_model_no = (self.manual_model_no or "").strip() or None
        self.manual_variant_no = (self.manual_variant_no or "").strip() or None
        self.kroy_no = (self.kroy_no or "").strip() or None
        self.section_name = (self.section_name or "").strip() or None
        if self.work_order_id is None:
            if self.sewing_assignment_id is not None:
                raise ValueError("A sewing assignment cannot be selected without a work order")
            if not self.manual_model_no:
                raise ValueError("Model number is required when no sewing order is attached")
        if self.sewn_qty <= 0:
            raise ValueError("Sewn quantity must be greater than zero")
        if self.section_quantities is not None:
            if any(quantity < 0 for quantity in self.section_quantities):
                raise ValueError("Section quantities cannot be negative")
            if sum(self.section_quantities) != self.sewn_qty:
                raise ValueError("Section quantities must add up to sewn quantity")
        if (self.top_qty is None) != (self.bottom_qty is None):
            raise ValueError("Top and bottom quantities must be provided together")
        if self.top_qty is not None and self.bottom_qty is not None:
            if self.top_qty + self.bottom_qty != self.sewn_qty:
                raise ValueError("Top and bottom quantities must add up to sewn quantity")
        if self.defective_qty > self.sewn_qty:
            raise ValueError("Defective quantity cannot exceed sewn quantity")
        if self.defective_qty > 0 and not (self.defect_reason or "").strip():
            raise ValueError("Defect reason is required when defective quantity is greater than zero")
        return self


class SewingDailyModelInfo(ORMModel):
    model_id: Optional[int] = None
    model_code: Optional[str] = None
    model_no: Optional[str] = None
    variant_no: Optional[str] = None
    model_name: Optional[str] = None
    model_image_url: Optional[str] = None
    fabric_image_url: Optional[str] = None


class SewingDailyReportOut(SewingDailyModelInfo):
    id: int
    report_date: date
    sewing_flow_id: int
    work_order_id: Optional[int] = None
    sewing_assignment_id: Optional[int] = None
    production_order_id: Optional[int] = None
    production_batch_id: Optional[int] = None
    line_code: str
    line_name: str
    order_no: Optional[str] = None
    production_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    manual_model_no: Optional[str] = None
    manual_variant_no: Optional[str] = None
    kroy_no: Optional[str] = None
    sewn_qty: int
    section_quantities: Optional[list[int]] = None
    section_no: Optional[int] = None
    section_name: Optional[str] = None
    top_qty: Optional[int] = None
    bottom_qty: Optional[int] = None
    defective_qty: int
    defect_reason: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class SewingDailyReportSummaryLine(SchemaModel):
    sewing_flow_id: int
    line_code: str
    line_name: str
    total_sewn_qty: int = 0
    total_defective_qty: int = 0
    report_count: int = 0
    order_count: int = 0
    orders: list[str] = Field(default_factory=list)
    models: list[SewingDailyModelInfo] = Field(default_factory=list)
    defect_reasons: list[str] = Field(default_factory=list)
    kroy_nos: list[str] = Field(default_factory=list)


class SewingDailyReportListOut(SchemaModel):
    from_date: date
    to_date: date
    rows: list[SewingDailyReportOut]
    summary: list[SewingDailyReportSummaryLine]
    total_sewn_qty: int = 0
    total_defective_qty: int = 0


class SewingDailyLineWorkOrder(SewingDailyModelInfo):
    work_order_id: int
    sewing_assignment_id: Optional[int] = None
    production_order_id: int
    production_batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    batch_name: Optional[str] = None
    batch_index: Optional[int] = None
    order_no: Optional[str] = None
    production_no: Optional[str] = None
    sales_order_no: Optional[str] = None
    status: str
    planned_qty: int = 0
    completed_qty: int = 0
    remaining_qty: int = 0
    deadline: Optional[datetime] = None
    kroy_no: Optional[str] = None


class SewingDailyLineContext(SchemaModel):
    sewing_flow_id: int
    line_code: str
    line_name: str
    active_work_orders: list[SewingDailyLineWorkOrder] = Field(default_factory=list)
