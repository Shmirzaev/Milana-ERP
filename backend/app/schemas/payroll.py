from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


class PayrollPeriodIn(BaseModel):
    period_no: str | None = None
    name: str
    start_date: datetime
    end_date: datetime
    status: str = "open"
    notes: str | None = None


class PayrollPeriodUpdate(BaseModel):
    period_no: str | None = None
    name: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: str | None = None
    notes: str | None = None


class PayrollPeriodOut(ORMModel):
    id: int
    period_no: str
    name: str
    start_date: datetime
    end_date: datetime
    status: str
    created_by: int | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PayrollRecordIn(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    payroll_period_id: int | None = None
    scan_uid: str | None = None
    employee_id: int | None = None
    employee_user_id: int | None = None
    employee: Any = None
    work: Any = None
    scanned_at: datetime | None = None
    quantity: Decimal | float | int | str | None = None
    rate_per_piece: Decimal | float | int | str | None = None
    currency: str | None = "UZS"
    source: str | None = "payroll_scan"
    notes: str | None = None

    production_order_id: int | None = None
    sales_order_id: int | None = None
    work_order_id: int | None = None
    production_batch_id: int | None = None
    batch_id: int | None = None
    model_id: int | None = None
    production_no: str | None = None
    sales_order_no: str | None = None
    batch_no: str | None = None
    model_code: str | None = None
    operation_section: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None


class PayrollRecordBulkIn(BaseModel):
    payroll_period_id: int | None = None
    records: list[PayrollRecordIn] = Field(default_factory=list)


class PayrollRecordOut(ORMModel):
    id: int
    payroll_period_id: int | None = None
    scan_uid: str | None = None
    original_scan_uid: str | None = None
    employee_id: int
    employee_user_id: int | None = None
    employee_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    production_order_id: int | None = None
    sales_order_id: int | None = None
    work_order_id: int | None = None
    production_batch_id: int | None = None
    model_id: int | None = None
    production_no: str | None = None
    sales_order_no: str | None = None
    batch_no: str | None = None
    model_code: str | None = None
    operation_section: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    quantity: Decimal
    rate_per_piece: Decimal
    currency: str
    total_amount: Decimal
    scanned_by: int | None = None
    scanned_at: datetime
    source: str
    raw_employee_json: dict | None = None
    raw_work_json: dict | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    duplicate: bool = False


class PayrollBulkOut(BaseModel):
    records: list[PayrollRecordOut]
    created_count: int
    duplicate_count: int


class PayrollQrLabelIssueIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    label_uid: str
    payload: str | None = None
    production_order_id: int | None = None
    sales_order_id: int | None = None
    work_order_id: int | None = None
    production_batch_id: int | None = None
    model_id: int | None = None
    production_no: str | None = None
    sales_order_no: str | None = None
    batch_no: str | None = None
    model_code: str | None = None
    operation_section: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    sewing_flow_id: int | None = None
    sewing_line_code: str | None = None
    sewing_line_name: str | None = None
    cutting_passport_id: int | None = None
    cutting_passport_no: str | None = None
    size: str | None = None
    copy_index: int = 1
    quantity: Decimal = Decimal("0")
    rate_per_piece: Decimal = Decimal("0")
    currency: str = "UZS"


class PayrollQrLabelsIssueIn(BaseModel):
    labels: list[PayrollQrLabelIssueIn] = Field(default_factory=list, max_length=5000)


class PayrollQrIssuedLabelOut(BaseModel):
    label_uid: str
    qr_token: str


class PayrollQrLabelsIssueOut(BaseModel):
    issued_count: int
    labels: list[PayrollQrIssuedLabelOut]


class PayrollQrLabelOut(ORMModel):
    id: int
    label_uid: str
    qr_token: str
    payload: str | None = None
    production_order_id: int | None = None
    sales_order_id: int | None = None
    work_order_id: int | None = None
    production_batch_id: int | None = None
    model_id: int | None = None
    production_no: str | None = None
    sales_order_no: str | None = None
    batch_no: str | None = None
    model_code: str | None = None
    operation_section: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    sewing_flow_id: int | None = None
    sewing_line_code: str | None = None
    sewing_line_name: str | None = None
    cutting_passport_id: int | None = None
    cutting_passport_no: str | None = None
    size: str | None = None
    copy_index: int
    quantity: Decimal
    rate_per_piece: Decimal
    currency: str
    status: str
    payroll_record_id: int | None = None
    employee_id: int | None = None
    employee_name: str | None = None
    department_name: str | None = None
    payroll_status: str | None = None
    issued_at: datetime
    last_scanned_at: datetime | None = None
    returned_at: datetime | None = None
    return_count: int


class PayrollQrControlOut(BaseModel):
    items: list[PayrollQrLabelOut]
    total: int
    available_count: int
    scanned_count: int


class PayrollSummaryOperationOut(BaseModel):
    employee_id: int
    operation_section: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    currency: str
    records_count: int
    quantity: Decimal
    total_amount: Decimal


class PayrollSummaryEmployeeOut(BaseModel):
    employee_id: int
    employee_name: str
    department_id: int | None = None
    department_name: str | None = None
    currency: str
    records_count: int
    adjustment_count: int = 0
    quantity: Decimal
    piecework_amount: Decimal = Decimal("0")
    adjustment_amount: Decimal = Decimal("0")
    bonus_amount: Decimal = Decimal("0")
    deduction_amount: Decimal = Decimal("0")
    total_amount: Decimal
    operations: list[PayrollSummaryOperationOut] = Field(default_factory=list)


class PayrollSummaryOut(BaseModel):
    records_count: int
    adjustment_count: int = 0
    quantity: Decimal
    piecework_amount: Decimal = Decimal("0")
    adjustment_amount: Decimal = Decimal("0")
    bonus_amount: Decimal = Decimal("0")
    deduction_amount: Decimal = Decimal("0")
    total_amount: Decimal
    currency: str
    employees: list[PayrollSummaryEmployeeOut]


class PayrollAdjustmentIn(BaseModel):
    payroll_period_id: int | None = None
    employee_id: int
    adjustment_type: str | None = None
    amount: Decimal | float | int | str
    currency: str = "UZS"
    reason: str


class PayrollAdjustmentOut(ORMModel):
    id: int
    payroll_period_id: int | None = None
    employee_id: int
    adjustment_type: str
    amount: Decimal
    signed_amount: Decimal
    currency: str
    reason: str
    created_by: int | None = None
    created_at: datetime
