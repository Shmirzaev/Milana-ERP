from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.schemas import (
    User,
)
from app.libs.dto.people.payroll import (
    PayrollAdjustmentIn,
    PayrollAdjustmentOut,
    PayrollAdjustmentPageOut,
    PayrollBulkOut,
    PayrollControlScanIn,
    PayrollControlConfirmIn,
    PayrollNumericWorkScanIn,
    PayrollNumericWorkScanOut,
    PayrollPeriodIn,
    PayrollPeriodOut,
    PayrollPeriodUpdate,
    PayrollQrControlOut,
    PayrollQrLabelBatchDeleteIn,
    PayrollQrLabelBatchDeleteOut,
    PayrollQrLabelEditIn,
    PayrollQrLabelOut,
    PayrollQrLabelSplitIn,
    PayrollQrLabelSplitOut,
    PayrollQrLabelsIssueIn,
    PayrollQrLabelsIssueOut,
    OrderQrStatusOrderOption,
    OrderQrStatusOut,
    PayrollRecordBulkIn,
    PayrollRecordIn,
    PayrollRecordOut,
    PayrollRecordPageOut,
    PayrollRecordReversalIn,
    PayrollScanSplitIn,
    PayrollSummaryOut,
    SewingProductionReportOut,
    SewingProductionReportOptions,
)
from app.models.process_qr_export_service import ProcessQrExportIn
from app.models.payroll_reports_service import ReportLanguage
from app.libs.dto.people.payroll_split_correction import SplitAllocationOut, SplitAllocationUpdate
from app.models.payroll_split_correction_service import correct_split_allocation, read_split_allocation, render_split_allocation_labels
from app.models.payroll_labels_service import split_labels_print_response
from app.models.people import payroll_adjustments_service
from app.models.people import payroll_service

from app.models.people.payroll_service import (
    RECORD_STATUSES as RECORD_STATUSES,
    _canonical_payroll_reference as _canonical_payroll_reference,
    _canonical_payroll_snapshot as _canonical_payroll_snapshot,
    _canonical_snapshot_reference as _canonical_snapshot_reference,
    _dget as _dget,
    _filtered_record_query as _filtered_record_query,
    _load_employee_maps as _load_employee_maps,
    _map_payroll_snapshot_references as _map_payroll_snapshot_references,
    _normalize_production_batch_no as _normalize_production_batch_no,
    _present as _present,
    _serialize_record as _serialize_record,
    _to_int as _to_int,
    _to_text as _to_text,
)

from app.models.people.payroll_service import (
    _payroll_order_reference_match as _payroll_order_reference_match,
    _payroll_order_reference_variants as _payroll_order_reference_variants,
)

from app.models.people.payroll_service import (
    PAYROLL_QR_TOKEN_ID_WIDTH as PAYROLL_QR_TOKEN_ID_WIDTH,
    PAYROLL_QR_TOKEN_LENGTH as PAYROLL_QR_TOKEN_LENGTH,
    PAYROLL_WORK_TOKEN_PREFIX as PAYROLL_WORK_TOKEN_PREFIX,
    _numeric_qr_token as _numeric_qr_token,
    _order_qr_label_query as _order_qr_label_query,
    _qr_label_maps as _qr_label_maps,
    _qr_size_sort_key as _qr_size_sort_key,
    _serialize_qr_label as _serialize_qr_label,
    _to_decimal as _to_decimal,
    _work_qr_token as _work_qr_token,
)

from app.models.people.payroll_service import (
    _sewing_report_factory_code as _sewing_report_factory_code,
    _sewing_report_options as _sewing_report_options,
)

from app.models.people.payroll_service import (
    _filtered_sewing_production_report_query as _filtered_sewing_production_report_query,
    _sewing_production_report_items as _sewing_production_report_items,
    _sewing_report_base_query as _sewing_report_base_query,
    _sewing_report_product_quantity as _sewing_report_product_quantity,
    _sewing_salary_summary as _sewing_salary_summary,
)

from app.models.people.payroll_service import (
    PAYROLL_EMPLOYEE_TOKEN_PREFIX as PAYROLL_EMPLOYEE_TOKEN_PREFIX,
    _employee_qr_token as _employee_qr_token,
    _employee_scan_payload as _employee_scan_payload,
)

from app.models.people.payroll_service import (
    _qr_label_scan_payload as _qr_label_scan_payload,
)

from app.models.people.payroll_service import (
    _PayrollOrderLookup as _PayrollOrderLookup,
    _qr_label_order_lookup as _qr_label_order_lookup,
    _work_label_id_from_token as _work_label_id_from_token,
)

from app.models.people.payroll_service import (
    _adjustment_signed_amount as _adjustment_signed_amount,
    _filtered_adjustment_query as _filtered_adjustment_query,
)

from app.models.people import payroll_qr_service
from app.models.people.payroll_service import _canonicalize_payroll_input as _canonicalize_payroll_input, _issue_order_lookup as _issue_order_lookup

from app.models.people import payroll_records_service
from app.models.people.payroll_records_service import (
    MAX_PAYROLL_SNAPSHOT_BYTES as MAX_PAYROLL_SNAPSHOT_BYTES,
    MAX_PAYROLL_SNAPSHOT_DEPTH as MAX_PAYROLL_SNAPSHOT_DEPTH,
    PAYROLL_RECORD_COMPONENT_MAX as PAYROLL_RECORD_COMPONENT_MAX,
    PAYROLL_RECORD_TOTAL_MAX as PAYROLL_RECORD_TOTAL_MAX,
    PAYROLL_WORK_UNITS as PAYROLL_WORK_UNITS,
    _PERIOD_NOT_PRELOCKED as _PERIOD_NOT_PRELOCKED,
    _assert_period_accepts_records as _assert_period_accepts_records,
    _assert_record_numeric_components as _assert_record_numeric_components,
    _attach_period as _attach_period,
    _can_period_override as _can_period_override,
    _can_set_payable_values as _can_set_payable_values,
    _compact_field as _compact_field,
    _compact_number as _compact_number,
    _create_record_from_payload as _create_record_from_payload,
    _dedupe_key as _dedupe_key,
    _extra as _extra,
    _find_period as _find_period,
    _first as _first,
    _legacy_payroll_dedupe_keys as _legacy_payroll_dedupe_keys,
    _mark_qr_label_scanned as _mark_qr_label_scanned,
    _normalize_record_payload as _normalize_record_payload,
    _normalize_scan_uid as _normalize_scan_uid,
    _parse_compact_payload as _parse_compact_payload,
    _payload_dict as _payload_dict,
    _prepare_record_data as _prepare_record_data,
    _record_period_candidate as _record_period_candidate,
    _validate_and_enrich_record as _validate_and_enrich_record,
    _validate_payroll_snapshot as _validate_payroll_snapshot,
    _validated_record_total_amount as _validated_record_total_amount,
)
from app.models.people.payroll_service import MUTATION_LOCKED_PERIOD_STATUSES as MUTATION_LOCKED_PERIOD_STATUSES

from app.models.people.payroll_records_service import (
    _assert_control_not_voided as _assert_control_not_voided,
    _bulk_chunks as _bulk_chunks,
    _bulk_id_map as _bulk_id_map,
    _bulk_record_order_lookup as _bulk_record_order_lookup,
    _bulk_validation_context as _bulk_validation_context,
    _control_label_query as _control_label_query,
    _control_preview as _control_preview,
    _control_review_token as _control_review_token,
    _load_control_scan as _load_control_scan,
    _prelock_bulk_record_resources as _prelock_bulk_record_resources,
)

router = APIRouter(prefix="/payroll", tags=["payroll"])

# Payroll raw snapshots are retained and returned as open JSON objects. Keep
# legacy keys, but cap each persisted snapshot to 16 KiB of compact UTF-8 JSON
# and 16 nested object/array levels (counting the root object as level 1).

ADJUSTMENT_TYPES = payroll_adjustments_service.ADJUSTMENT_TYPES
PAYROLL_ADJUSTMENT_MAX_AMOUNT = payroll_adjustments_service.PAYROLL_ADJUSTMENT_MAX_AMOUNT






















_to_money_decimal = payroll_adjustments_service._to_money_decimal


_normalize_adjustment_amount = payroll_adjustments_service._normalize_adjustment_amount






















































_assert_period_accepts_adjustments = payroll_adjustments_service._assert_period_accepts_adjustments

























@router.get("/periods", response_model=list[PayrollPeriodOut])
def list_periods(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.approve", "payroll.pay", "*")),
    status: str | None = None,
):
    return payroll_service.list_periods(db, current, status)


@router.post("/periods", response_model=PayrollPeriodOut, status_code=201)
def create_period(
    payload: PayrollPeriodIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_service.create_period(payload, db, current)


@router.patch("/periods/{period_id}", response_model=PayrollPeriodOut)
def update_period(
    period_id: int,
    payload: PayrollPeriodUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_service.update_period(period_id, payload, db, current)


@router.post("/periods/{period_id}/lock", response_model=PayrollPeriodOut)
def lock_period(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_service.lock_period(period_id, db, current)


@router.post("/periods/{period_id}/approve", response_model=PayrollPeriodOut)
def approve_period(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.approve", "*")),
):
    return payroll_service.approve_period(period_id, db, current)


@router.post("/periods/{period_id}/mark-paid", response_model=PayrollPeriodOut)
def mark_period_paid(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.pay", "*")),
):
    return payroll_service.mark_period_paid(period_id, db, current)


@router.get("/records", response_model=list[PayrollRecordOut] | PayrollRecordPageOut)
def list_records(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    limit: int = 200,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    return payroll_service.list_records(db, current, period_id, employee_id, department_id, date_from, date_to, status, limit, page, page_size)











@router.get("/reports/order-qr-status/orders", response_model=list[OrderQrStatusOrderOption])
def order_qr_status_orders(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    search: str | None = None,
    limit: int = 50,
):
    return payroll_service.order_qr_status_orders(db, current, search, limit)


@router.get("/reports/order-qr-status", response_model=OrderQrStatusOut)
def order_qr_status_report(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    order_no: str = "",
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    return payroll_service.order_qr_status_report(db, current, order_no, status, limit, offset)








@router.get("/reports/sewing-production/options", response_model=SewingProductionReportOptions)
def sewing_production_report_options(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    factory_code: str | None = None,
):
    return payroll_service.sewing_production_report_options(db, current, factory_code)










@router.get("/reports/sewing-production", response_model=SewingProductionReportOut)
def sewing_production_report(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    employee_id: int | None = None,
    order_no: str | None = None,
    cutting_reference: str | None = None,
    model_code: str | None = None,
    sewing_flow_id: int | None = None,
    sewing_line: str | None = None,
    operation: str | None = None,
    barcode: str | None = None,
    size: str | None = None,
    factory_code: str | None = None,
    status: str = "active",
    report_view: Literal["details", "salary"] = "details",
    limit: int = 100,
    offset: int = 0,
):
    return payroll_service.sewing_production_report(db, current, date_from, date_to, employee_id, order_no, cutting_reference, model_code, sewing_flow_id, sewing_line, operation, barcode, size, factory_code, status, report_view, limit, offset)


@router.get("/reports/sewing-production.xlsx")
def sewing_production_report_excel(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    lang: ReportLanguage = "uz",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    employee_id: int | None = None,
    order_no: str | None = None,
    cutting_reference: str | None = None,
    model_code: str | None = None,
    sewing_flow_id: int | None = None,
    sewing_line: str | None = None,
    operation: str | None = None,
    barcode: str | None = None,
    size: str | None = None,
    factory_code: str | None = None,
    status: str = "active",
    report_view: Literal["details", "salary"] = "details",
):
    workbook, filename = payroll_service.sewing_production_report_excel(db, current, lang, date_from, date_to, employee_id, order_no, cutting_reference, model_code, sewing_flow_id, sewing_line, operation, barcode, size, factory_code, status, report_view)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/process-qr/export.xlsx")
def export_process_qr_operations(
    payload: ProcessQrExportIn,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    workbook = payroll_service.export_process_qr_operations(payload, current)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="paid-processes.xlsx"'},
    )


@router.post("/qr-labels/issue", response_model=PayrollQrLabelsIssueOut)
def issue_qr_labels(
    payload: PayrollQrLabelsIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_qr_service.issue_qr_labels(payload, db, current)





@router.get("/employees/search")
def search_payroll_employees(
    db: DbSession,
    q: str = Query(min_length=2, max_length=100),
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_service.search_payroll_employees(db, q, current)


@router.get("/employees/resolve")
def resolve_employee_number(
    employee_no: str,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_service.resolve_employee_number(employee_no, db, current)














@router.post("/scan/control-preview")
def preview_control_scan(
    payload: PayrollControlScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.preview_control_scan(payload, db, current)


@router.post("/scan/control-confirm", response_model=PayrollRecordOut, status_code=201)
def confirm_control_scan(
    payload: PayrollControlConfirmIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.confirm_control_scan(payload, db, current)


@router.post("/scan/numeric-work", response_model=PayrollNumericWorkScanOut, status_code=201)
def record_numeric_work_scan(
    payload: PayrollNumericWorkScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.record_numeric_work_scan(payload, db, current)


@router.get("/qr/resolve/{token}")
def resolve_qr_token(
    token: str,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_service.resolve_qr_token(token, db, current)






@router.get("/qr-labels", response_model=PayrollQrControlOut)
def list_qr_labels(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.scan", "payroll.manage", "*")),
    search: str | None = None,
    status: str | None = None,
    order_no: str | None = None,
    production_order_id: int | None = None,
    include_superseded: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    return payroll_service.list_qr_labels(db, current, search, status, order_no, production_order_id, include_superseded, limit, offset)


_assert_qr_label_never_scanned = payroll_qr_service._assert_qr_label_never_scanned


_corrected_label_values = payroll_qr_service._corrected_label_values


@router.patch("/qr-labels/{label_id}", response_model=PayrollQrLabelOut)
def edit_qr_label(
    label_id: int,
    payload: PayrollQrLabelEditIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_qr_service.edit_qr_label(label_id, payload, db, current)


@router.post("/qr-labels/{label_id}/split", response_model=PayrollQrLabelSplitOut)
def split_qr_label(
    label_id: int,
    payload: PayrollQrLabelSplitIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_qr_service.split_qr_label(label_id, payload, db, current)


@router.post("/qr-labels/delete-batch", response_model=PayrollQrLabelBatchDeleteOut)
def delete_qr_label_batch(
    payload: PayrollQrLabelBatchDeleteIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_qr_service.delete_qr_label_batch(payload, db, current)


@router.post("/qr-labels/{label_id}/return", response_model=PayrollQrLabelOut)
def return_qr_label(
    label_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
    expected_record_id: int | None = None,
):
    return payroll_records_service.return_qr_label(label_id, db, current, expected_record_id)


@router.post("/records", response_model=PayrollRecordOut, status_code=201)
def create_record(
    payload: PayrollRecordIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.create_record(payload, db, current)





@router.post("/records/bulk", response_model=PayrollBulkOut)
def create_records_bulk(
    payload: PayrollRecordBulkIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.create_records_bulk(payload, db, current)


@router.get("/qr-labels/{label_id}/split-allocation", response_model=SplitAllocationOut)
def get_split_allocation(label_id: int, db: DbSession,
                         current: User = Depends(require_permissions("payroll.manage", "*"))):
    return read_split_allocation(db, actor=current, label_id=label_id)


@router.patch("/qr-labels/{label_id}/split-allocation", response_model=SplitAllocationOut)
def patch_split_allocation(label_id: int, payload: SplitAllocationUpdate, db: DbSession,
                           current: User = Depends(require_permissions("payroll.manage", "*"))):
    return correct_split_allocation(db, actor=current, label_id=label_id, payload=payload)


@router.get("/qr-labels/{label_id}/split-allocation/print")
def print_split_allocation(label_id: int, db: DbSession,
                           current: User = Depends(require_permissions("payroll.manage", "*"))):
    return split_labels_print_response(render_split_allocation_labels(
        db, actor=current, label_id=label_id, token_for_label=_work_qr_token))


@router.post("/records/{record_id}/split", response_model=list[PayrollRecordOut])
def split_scanned_record(
    record_id: int,
    payload: PayrollScanSplitIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return payroll_records_service.split_scanned_record(record_id, payload, db, current)


@router.get("/records/{record_id}/split-labels/print")
def print_split_record_labels(record_id: int, db: DbSession,
                              current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*"))):
    from fastapi.responses import HTMLResponse
    markup = payroll_service.print_split_record_labels(record_id, db, current)
    return HTMLResponse(markup, headers={"Cache-Control": "no-store"})


@router.post("/records/{record_id}/void", response_model=PayrollRecordOut)
def void_record(
    record_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_records_service.void_record(record_id, db, current)


@router.post("/records/{record_id}/reverse-as-adjustment", response_model=PayrollAdjustmentOut, status_code=201)
def reverse_record_as_adjustment(
    record_id: int,
    payload: PayrollRecordReversalIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_adjustments_service.reverse_record_as_adjustment(record_id, payload, db, current)


@router.get("/summary", response_model=PayrollSummaryOut)
def payroll_summary(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    group_by_operation: bool = True,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
    employee_search: Annotated[str | None, Query(max_length=100)] = None,
):
    return payroll_service.payroll_summary(db, current, period_id, employee_id, department_id, date_from, date_to, group_by_operation, page, page_size, employee_search)



@router.get("/adjustments", response_model=list[PayrollAdjustmentOut] | PayrollAdjustmentPageOut)
def list_adjustments(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    return payroll_service.list_adjustments(db, current, period_id, employee_id, department_id, date_from, date_to, page, page_size)



@router.post("/adjustments", response_model=PayrollAdjustmentOut, status_code=201)
def create_adjustment(
    payload: PayrollAdjustmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    return payroll_adjustments_service.create_adjustment(payload, db, current)


@router.delete("/adjustments/{adjustment_id}", status_code=204)
def delete_adjustment(
    adjustment_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    payroll_adjustments_service.delete_adjustment(adjustment_id, db, current)
    return Response(status_code=204)


@router.get("/employees/options")
def list_payroll_employee_options(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.approve", "payroll.pay", "*")),
    search: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 50,
    selected_id: Annotated[int | None, Query(ge=1)] = None,
):
    return payroll_service.list_payroll_employee_options(db, current, search, page, page_size, selected_id)
