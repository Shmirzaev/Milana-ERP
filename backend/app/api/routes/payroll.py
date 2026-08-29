from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, or_

from app.core.deps import DbSession, require_permissions, is_admin, user_permissions
from app.core.dt import as_utc, utcnow
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.models import (
    Bundle,
    Department,
    Employee,
    Model,
    PayrollAdjustment,
    PayrollPeriod,
    PayrollQrLabel,
    PayrollRecord,
    ProductionBatch,
    ProductionOrder,
    SalesOrder,
    SewingFlow,
    User,
    WorkOrder,
)
from app.schemas.payroll import (
    PayrollAdjustmentIn,
    PayrollAdjustmentOut,
    PayrollBulkOut,
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
    PayrollRecordReversalIn,
    PayrollSummaryEmployeeOut,
    PayrollSummaryOperationOut,
    PayrollSummaryOut,
    SewingProductionReportOut,
    SewingProductionReportOptions,
)
from app.services.audit import log_action
from app.services.factory_scope import require_factory_access, selected_factory_code
from app.services.paid_operations import filter_operation_rows, paid_operations_from_details
from app.services.payroll_factory_scope import require_production_order_factory, require_work_order_factory
from app.services.payroll_reports import ReportLanguage, build_sewing_production_report_xlsx

router = APIRouter(prefix="/payroll", tags=["payroll"])

PERIOD_STATUSES = {"draft", "open", "locked", "approved", "paid", "cancelled"}
PERIOD_CREATE_STATUSES = {"draft", "open"}
PERIOD_MANAGE_STATUS_TRANSITIONS = {
    "draft": {"draft", "open", "cancelled"},
    "open": {"draft", "open", "cancelled"},
    "locked": {"open", "locked", "cancelled"},
    "approved": {"approved"},
    "paid": {"paid"},
    "cancelled": {"cancelled"},
}
RECORD_STATUSES = {"recorded", "voided", "approved", "paid"}
MUTATION_LOCKED_PERIOD_STATUSES = {"locked", "approved", "paid", "cancelled"}
ADJUSTMENT_TYPES = {"bonus", "deduction"}
PAYROLL_WORK_UNITS = {"piece", "work_unit"}
PAYROLL_QR_TOKEN_LENGTH = 9
PAYROLL_EMPLOYEE_TOKEN_PREFIX = "1"
PAYROLL_WORK_TOKEN_PREFIX = "2"
PAYROLL_QR_TOKEN_ID_WIDTH = PAYROLL_QR_TOKEN_LENGTH - 1


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _to_int(value: Any) -> int | None:
    if not _present(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_text(value: Any) -> str | None:
    if not _present(value):
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if not _present(value):
        return default
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(400, f"Invalid numeric value: {value}")
    if amount < 0:
        raise HTTPException(400, "Payroll quantity and rates must be non-negative")
    return amount


def _numeric_qr_token(prefix: str, record_id: int) -> str:
    if record_id <= 0 or record_id >= 10**PAYROLL_QR_TOKEN_ID_WIDTH:
        raise HTTPException(500, "Payroll QR identifier is outside the supported range")
    return f"{prefix}{record_id:0{PAYROLL_QR_TOKEN_ID_WIDTH}d}"


def _employee_qr_token(employee_id: int) -> str:
    return _numeric_qr_token(PAYROLL_EMPLOYEE_TOKEN_PREFIX, employee_id)


def _work_qr_token(label_id: int) -> str:
    return _numeric_qr_token(PAYROLL_WORK_TOKEN_PREFIX, label_id)


def _work_label_id_from_token(token: str) -> int | None:
    normalized = token.strip()
    if len(normalized) != PAYROLL_QR_TOKEN_LENGTH or not normalized.isdigit():
        return None
    if not normalized.startswith(PAYROLL_WORK_TOKEN_PREFIX):
        return None
    return int(normalized[1:])


def _to_money_decimal(value: Any) -> Decimal:
    if not _present(value):
        raise HTTPException(400, "amount is required")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(400, f"Invalid numeric value: {value}")


def _normalize_adjustment_amount(payload: PayrollAdjustmentIn) -> tuple[Decimal, str]:
    raw_amount = _to_money_decimal(payload.amount)
    adjustment_type = (payload.adjustment_type or "").strip().lower()
    if adjustment_type and adjustment_type not in ADJUSTMENT_TYPES:
        raise HTTPException(400, "adjustment_type must be bonus or deduction")
    if raw_amount == 0:
        raise HTTPException(400, "Adjustment amount must be non-zero")
    if raw_amount < 0:
        if adjustment_type == "bonus":
            raise HTTPException(400, "Negative adjustments must use adjustment_type=deduction")
        return abs(raw_amount), "deduction"
    return raw_amount, adjustment_type or "bonus"


def _adjustment_signed_amount(adjustment: PayrollAdjustment) -> Decimal:
    amount = adjustment.amount or Decimal("0")
    return -amount if adjustment.adjustment_type == "deduction" else amount


def _compact_field(value: str | None) -> str | None:
    text = _to_text(value)
    if text in (None, "-"):
        return None
    return text


def _compact_number(value: str | None) -> int | None:
    return _to_int(_compact_field(value))


def _normalize_production_batch_no(value: Any) -> str | None:
    text = _to_text(value)
    if text and text.upper().startswith("BT-"):
        return text[3:] or None
    return text


def _parse_compact_payload(raw: str) -> dict[str, Any] | None:
    parts = raw.strip().split("*")
    kind = str(parts[0] if parts else "").upper()
    if kind == "ME2":
        employee_id = _compact_number(parts[1] if len(parts) > 1 else None)
        if employee_id is None:
            return None
        return {
            "type": "employee_payroll",
            "source": "milana_erp_compact",
            "employee_id": employee_id,
            "user_id": _compact_number(parts[2] if len(parts) > 2 else None),
            "employee_name": _compact_field(parts[3] if len(parts) > 3 else None) or f"Employee {employee_id}",
            "department_id": _compact_number(parts[4] if len(parts) > 4 else None),
            "department_name": _compact_field(parts[5] if len(parts) > 5 else None),
            "position": _compact_field(parts[6] if len(parts) > 6 else None),
            "status": _compact_field(parts[7] if len(parts) > 7 else None),
            "copy_index": _compact_number(parts[8] if len(parts) > 8 else None),
        }
    if kind == "MW2":
        return {
            "type": "process_payroll",
            "source": "milana_erp_compact",
            "production_order_id": _compact_number(parts[1] if len(parts) > 1 else None),
            "production_no": _compact_field(parts[2] if len(parts) > 2 else None),
            "batch_id": _compact_number(parts[3] if len(parts) > 3 else None),
            "batch_no": _normalize_production_batch_no(_compact_field(parts[4] if len(parts) > 4 else None)),
            "batch_index": _compact_number(parts[5] if len(parts) > 5 else None),
            "model_code": _compact_field(parts[6] if len(parts) > 6 else None),
            "operation_section": _compact_field(parts[7] if len(parts) > 7 else None),
            "operation_code": _compact_field(parts[8] if len(parts) > 8 else None),
            "operation_name": _compact_field(parts[9] if len(parts) > 9 else None),
            "quantity": _compact_field(parts[10] if len(parts) > 10 else None),
            "rate_per_piece": _compact_field(parts[11] if len(parts) > 11 else None),
            "currency": _compact_field(parts[12] if len(parts) > 12 else None) or "UZS",
            "copy_index": _compact_number(parts[13] if len(parts) > 13 else None),
            "sales_order_id": _compact_number(parts[14] if len(parts) > 14 else None),
            "sales_order_no": _compact_field(parts[15] if len(parts) > 15 else None),
            "work_order_id": _compact_number(parts[16] if len(parts) > 16 else None),
            "model_id": _compact_number(parts[17] if len(parts) > 17 else None),
            "label_id": _compact_field(parts[18] if len(parts) > 18 else None),
            "size": _compact_field(parts[19] if len(parts) > 19 else None),
            "sewing_flow_id": _compact_number(parts[20] if len(parts) > 20 else None),
            "sewing_line_code": _compact_field(parts[21] if len(parts) > 21 else None),
            "sewing_line_name": _compact_field(parts[22] if len(parts) > 22 else None),
            "cutting_passport_id": _compact_number(parts[23] if len(parts) > 23 else None),
            "cutting_passport_no": _compact_field(parts[24] if len(parts) > 24 else None),
        }
    return None


def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        compact = _parse_compact_payload(value)
        if compact:
            return compact
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _extra(payload: PayrollRecordIn, key: str) -> Any:
    return (payload.model_extra or {}).get(key)


def _first(*values: Any) -> Any:
    for value in values:
        if _present(value):
            return value
    return None


def _dget(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if _present(value):
            return value
    return None


def _normalize_scan_uid(payload: PayrollRecordIn, work_payload: dict[str, Any]) -> str | None:
    return _to_text(
        _first(
            _dget(work_payload, "label_id"),
            payload.scan_uid,
            _extra(payload, "scanUid"),
            _extra(payload, "id"),
            _dget(work_payload, "scan_uid", "scanUid", "id"),
        )
    )


def _normalize_record_payload(payload: PayrollRecordIn) -> dict[str, Any]:
    employee_payload = _payload_dict(
        _first(
            payload.employee,
            _extra(payload, "raw_employee"),
            _extra(payload, "rawEmployee"),
            _extra(payload, "employee_payload"),
            _extra(payload, "employeePayload"),
        )
    )
    work_payload = _payload_dict(
        _first(
            payload.work,
            _extra(payload, "raw_work"),
            _extra(payload, "rawWork"),
            _extra(payload, "work_payload"),
            _extra(payload, "workPayload"),
        )
    )

    employee_id = _to_int(_first(payload.employee_id, _extra(payload, "employeeId"), _dget(employee_payload, "employee_id", "e")))
    employee_user_id = _to_int(
        _first(
            payload.employee_user_id,
            _extra(payload, "employeeUserId"),
            _dget(employee_payload, "employee_user_id", "user_id", "u"),
        )
    )
    scanned_at = payload.scanned_at or _extra(payload, "scannedAt") or utcnow()
    if isinstance(scanned_at, str):
        try:
            scanned_at = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(400, f"Invalid scanned_at value: {scanned_at}") from e
    scanned_at = as_utc(scanned_at) or utcnow()

    production_batch_id = _to_int(
        _first(
            payload.production_batch_id,
            payload.batch_id,
            _extra(payload, "productionBatchId"),
            _extra(payload, "batchId"),
            _dget(work_payload, "production_batch_id", "batch_id", "bi"),
        )
    )
    payroll_unit = (
        _to_text(_first(_extra(payload, "payroll_unit"), _extra(payload, "payrollUnit"), _dget(work_payload, "payroll_unit", "payrollUnit", "unit_type")))
        or "piece"
    ).lower()
    if payroll_unit not in PAYROLL_WORK_UNITS:
        raise HTTPException(400, "Payroll work QR must represent one payable piece/work_unit")
    quantity = _to_decimal(_first(payload.quantity, _extra(payload, "qty"), _dget(work_payload, "quantity", "q")), Decimal("0"))
    if quantity <= 0:
        raise HTTPException(400, "Payroll work QR must include a positive payable quantity")
    rate = _to_decimal(
        _first(
            payload.rate_per_piece,
            _extra(payload, "ratePerPiece"),
            _extra(payload, "rate"),
            _dget(work_payload, "rate_per_piece", "rate", "r"),
        ),
        Decimal("0"),
    )
    currency = (_to_text(_first(payload.currency, _dget(work_payload, "currency", "c"))) or "UZS").upper()[:8]

    return {
        "scan_uid": _normalize_scan_uid(payload, work_payload),
        "employee_id": employee_id,
        "employee_user_id": employee_user_id,
        "production_order_id": _to_int(
            _first(payload.production_order_id, _extra(payload, "productionOrderId"), _dget(work_payload, "production_order_id", "pid"))
        ),
        "sales_order_id": _to_int(_first(payload.sales_order_id, _extra(payload, "salesOrderId"), _dget(work_payload, "sales_order_id", "soid"))),
        "work_order_id": _to_int(_first(payload.work_order_id, _extra(payload, "workOrderId"), _dget(work_payload, "work_order_id", "wid"))),
        "production_batch_id": production_batch_id,
        "model_id": _to_int(_first(payload.model_id, _extra(payload, "modelId"), _dget(work_payload, "model_id", "mid"))),
        "production_no": _to_text(_first(payload.production_no, _extra(payload, "productionNo"), _dget(work_payload, "production_no", "po"))),
        "sales_order_no": _to_text(_first(payload.sales_order_no, _extra(payload, "salesOrderNo"), _dget(work_payload, "sales_order_no", "so"))),
        "batch_no": _normalize_production_batch_no(_first(payload.batch_no, _extra(payload, "batchNo"), _dget(work_payload, "batch_no", "batch_key", "b", "bk"))),
        "model_code": _to_text(_first(payload.model_code, _extra(payload, "modelCode"), _dget(work_payload, "model_code", "m"))),
        "operation_section": _to_text(
            _first(payload.operation_section, _extra(payload, "operationSection"), _dget(work_payload, "operation_section", "section", "s"))
        ),
        "operation_code": _to_text(_first(payload.operation_code, _extra(payload, "operationCode"), _dget(work_payload, "operation_code", "oc"))),
        "operation_name": _to_text(_first(payload.operation_name, _extra(payload, "operationName"), _dget(work_payload, "operation_name", "on"))),
        "quantity": quantity,
        "rate_per_piece": rate,
        "currency": currency,
        "total_amount": (quantity * rate).quantize(Decimal("0.01")),
        "scanned_at": scanned_at,
        "source": _to_text(payload.source) or "payroll_scan",
        "notes": _to_text(payload.notes),
        "raw_employee_json": employee_payload or None,
        "raw_work_json": work_payload or None,
    }


def _period_no_for(db: DbSession, start_date: datetime, factory_code: str) -> str:
    base = f"PAY-{start_date.year}-{start_date.month:02d}"
    if not db.query(PayrollPeriod.id).filter(
        PayrollPeriod.factory_code == factory_code,
        PayrollPeriod.period_no == base,
    ).first():
        return base
    year_prefix = f"PAY-{start_date.year}-"
    count = db.query(PayrollPeriod.id).filter(
        PayrollPeriod.factory_code == factory_code,
        PayrollPeriod.period_no.like(f"{year_prefix}%"),
    ).count() + 1
    while True:
        candidate = f"{year_prefix}{count:06d}"
        if not db.query(PayrollPeriod.id).filter(
            PayrollPeriod.factory_code == factory_code,
            PayrollPeriod.period_no == candidate,
        ).first():
            return candidate
        count += 1


def _validate_period_dates(start_date: datetime, end_date: datetime) -> None:
    if as_utc(end_date) < as_utc(start_date):
        raise HTTPException(400, "Payroll period end_date must be after start_date")


def _can_period_override(user: User) -> bool:
    perms = user_permissions(user)
    return is_admin(user) or "management.approve" in perms or "payroll.approve" in perms


def _attach_period(
    db: DbSession,
    period_id: int | None,
    scanned_at: datetime,
    factory_code: str,
) -> PayrollPeriod | None:
    if period_id:
        period = db.query(PayrollPeriod).filter(
            PayrollPeriod.id == period_id,
            PayrollPeriod.factory_code == factory_code,
        ).first()
        if not period:
            raise HTTPException(404, "Payroll period not found")
        return period

    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.factory_code == factory_code,
            PayrollPeriod.status == "open",
            PayrollPeriod.start_date <= scanned_at,
            PayrollPeriod.end_date >= scanned_at,
        )
        .order_by(PayrollPeriod.id.desc())
        .first()
    )
    if period:
        return period
    return (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.factory_code == factory_code, PayrollPeriod.status == "open")
        .order_by(PayrollPeriod.id.desc())
        .first()
    )


def _assert_period_accepts_records(period: PayrollPeriod | None, user: User) -> None:
    if not period:
        return
    if period.status == "locked" and _can_period_override(user):
        return
    if period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")


def _assert_period_accepts_adjustments(period: PayrollPeriod | None) -> None:
    if not period:
        return
    if period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")


def _dedupe_key(data: dict[str, Any]) -> str:
    payload = {
        "factory_code": data.get("factory_code"),
        "scan_uid": data.get("scan_uid"),
        "employee_id": data.get("employee_id"),
        "employee_user_id": data.get("employee_user_id"),
        "production_order_id": data.get("production_order_id"),
        "sales_order_id": data.get("sales_order_id"),
        "work_order_id": data.get("work_order_id"),
        "production_batch_id": data.get("production_batch_id"),
        "model_id": data.get("model_id"),
        "production_no": data.get("production_no"),
        "sales_order_no": data.get("sales_order_no"),
        "batch_no": data.get("batch_no"),
        "model_code": data.get("model_code"),
        "operation_section": data.get("operation_section"),
        "operation_code": data.get("operation_code"),
        "operation_name": data.get("operation_name"),
        "scanned_at": (as_utc(data.get("scanned_at")) or data.get("scanned_at")).isoformat(),
        "quantity": str(data.get("quantity")),
        "rate_per_piece": str(data.get("rate_per_piece")),
        "currency": data.get("currency"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_and_enrich_record(db: DbSession, data: dict[str, Any], factory_code: str) -> dict[str, Any]:
    employee_id = data.get("employee_id")
    if not employee_id:
        raise HTTPException(400, "employee_id is required")
    employee = db.query(Employee).filter(
        Employee.id == int(employee_id),
        Employee.factory_code == factory_code,
    ).first()
    if not employee:
        raise HTTPException(404, "Employee not found")
    if not data.get("employee_user_id") and employee.user_id:
        data["employee_user_id"] = employee.user_id
    if data.get("employee_user_id"):
        employee_user = db.query(User).filter(
            User.id == int(data["employee_user_id"]),
            User.factory_code == factory_code,
        ).first()
        if not employee_user:
            raise HTTPException(404, "Employee user not found")

    wo = db.get(WorkOrder, int(data["work_order_id"])) if data.get("work_order_id") else None
    if data.get("work_order_id") and not wo:
        raise HTTPException(404, "Work order not found")
    if wo:
        require_work_order_factory(db, wo, factory_code)
        if data.get("production_order_id") and int(data["production_order_id"]) != int(wo.production_order_id):
            raise HTTPException(400, "work_order_id does not belong to production_order_id")
        if wo.production_batch_id and data.get("production_batch_id") and int(data["production_batch_id"]) != int(wo.production_batch_id):
            raise HTTPException(400, "production_batch_id does not belong to work_order_id")
        data["production_order_id"] = wo.production_order_id
        data["production_batch_id"] = data.get("production_batch_id") or wo.production_batch_id
        data["operation_section"] = data.get("operation_section") or wo.operation

    po = db.get(ProductionOrder, int(data["production_order_id"])) if data.get("production_order_id") else None
    if data.get("production_order_id") and not po:
        raise HTTPException(404, "Production order not found")
    if po:
        require_production_order_factory(db, int(po.id), factory_code)
        data["production_no"] = data.get("production_no") or po.production_no
        data["sales_order_id"] = data.get("sales_order_id") or po.sales_order_id
        data["model_id"] = data.get("model_id") or po.model_id

    so = db.get(SalesOrder, int(data["sales_order_id"])) if data.get("sales_order_id") else None
    if data.get("sales_order_id") and not so:
        raise HTTPException(404, "Sales order not found")
    if so:
        data["sales_order_no"] = data.get("sales_order_no") or so.order_no

    batch = db.get(ProductionBatch, int(data["production_batch_id"])) if data.get("production_batch_id") else None
    if data.get("production_batch_id") and not batch:
        raise HTTPException(404, "Production batch not found")
    if batch:
        if data.get("production_order_id") and int(batch.production_order_id) != int(data["production_order_id"]):
            raise HTTPException(400, "production_batch_id does not belong to production_order_id")
        data["production_order_id"] = data.get("production_order_id") or batch.production_order_id
        data["batch_no"] = data.get("batch_no") or batch.batch_no

    model = db.get(Model, int(data["model_id"])) if data.get("model_id") else None
    if data.get("model_id") and not model:
        raise HTTPException(404, "Model not found")
    if model:
        data["model_code"] = data.get("model_code") or model.code

    issued_label = None
    if data.get("scan_uid"):
        issued_label = (
            db.query(PayrollQrLabel)
            .filter(
                PayrollQrLabel.label_uid == data["scan_uid"],
                PayrollQrLabel.factory_code == factory_code,
            )
            .with_for_update()
            .one_or_none()
        )
    if issued_label:
        if issued_label.status == "superseded":
            raise HTTPException(409, "This payroll QR was replaced by split labels and can no longer be scanned")
        if issued_label.status != "available":
            raise HTTPException(409, "This payroll QR is not available for scanning")
        data.update({
            "production_order_id": issued_label.production_order_id,
            "sales_order_id": issued_label.sales_order_id,
            "work_order_id": issued_label.work_order_id,
            "production_batch_id": issued_label.production_batch_id,
            "model_id": issued_label.model_id,
            "production_no": issued_label.production_no,
            "sales_order_no": issued_label.sales_order_no,
            "batch_no": _normalize_production_batch_no(issued_label.batch_no),
            "model_code": issued_label.model_code,
            "operation_section": issued_label.operation_section,
            "operation_code": issued_label.operation_code,
            "operation_name": issued_label.operation_name,
            "quantity": _to_decimal(issued_label.quantity),
            "rate_per_piece": _to_decimal(issued_label.rate_per_piece),
            "currency": issued_label.currency,
        })
        data["total_amount"] = (data["quantity"] * data["rate_per_piece"]).quantize(Decimal("0.01"))
        raw_work = dict(data.get("raw_work_json") or {})
        raw_work.update({
            "sewing_flow_id": issued_label.sewing_flow_id,
            "sewing_line_code": issued_label.sewing_line_code,
            "sewing_line_name": issued_label.sewing_line_name,
            "cutting_passport_id": issued_label.cutting_passport_id,
            "cutting_passport_no": issued_label.cutting_passport_no,
            "size": issued_label.size,
            "copy_index": issued_label.copy_index,
        })
        data["raw_work_json"] = raw_work

    data["factory_code"] = factory_code
    data["operation_name"] = data.get("operation_name") or data.get("operation_code") or data.get("operation_section")
    data["dedupe_key"] = _dedupe_key(data)
    return data


def _load_employee_maps(db: DbSession, employee_ids: set[int]) -> tuple[dict[int, Employee], dict[int, Department]]:
    employees = {
        int(e.id): e
        for e in (db.query(Employee).filter(Employee.id.in_(employee_ids)).all() if employee_ids else [])
    }
    department_ids = {int(e.department_id) for e in employees.values() if e.department_id}
    departments = {
        int(d.id): d
        for d in (db.query(Department).filter(Department.id.in_(department_ids)).all() if department_ids else [])
    }
    return employees, departments


def _serialize_record(
    record: PayrollRecord,
    *,
    duplicate: bool = False,
    employees: dict[int, Employee] | None = None,
    departments: dict[int, Department] | None = None,
) -> dict[str, Any]:
    employee = (employees or {}).get(int(record.employee_id))
    department = None
    if employee and employee.department_id:
        department = (departments or {}).get(int(employee.department_id))
    return {
        "id": record.id,
        "factory_code": record.factory_code,
        "payroll_period_id": record.payroll_period_id,
        "scan_uid": record.scan_uid,
        "original_scan_uid": record.original_scan_uid,
        "employee_id": record.employee_id,
        "employee_user_id": record.employee_user_id,
        "employee_name": employee.full_name if employee else None,
        "department_id": employee.department_id if employee else None,
        "department_name": department.name if department else None,
        "production_order_id": record.production_order_id,
        "sales_order_id": record.sales_order_id,
        "work_order_id": record.work_order_id,
        "production_batch_id": record.production_batch_id,
        "model_id": record.model_id,
        "production_no": record.production_no,
        "sales_order_no": record.sales_order_no,
        "batch_no": _normalize_production_batch_no(record.batch_no),
        "model_code": record.model_code,
        "operation_section": record.operation_section,
        "operation_code": record.operation_code,
        "operation_name": record.operation_name,
        "quantity": record.quantity,
        "rate_per_piece": record.rate_per_piece,
        "currency": record.currency,
        "total_amount": record.total_amount,
        "scanned_by": record.scanned_by,
        "scanned_at": record.scanned_at,
        "source": record.source,
        "raw_employee_json": record.raw_employee_json,
        "raw_work_json": record.raw_work_json,
        "status": record.status,
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "duplicate": duplicate,
    }


def _mark_qr_label_scanned(db: DbSession, record: PayrollRecord, data: dict[str, Any]) -> None:
    label_uid = _to_text(record.scan_uid)
    if not label_uid:
        return
    raw_work = data.get("raw_work_json") if isinstance(data.get("raw_work_json"), dict) else {}
    label = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.label_uid == label_uid,
        PayrollQrLabel.factory_code == record.factory_code,
    ).first()
    if not label:
        label = PayrollQrLabel(
            factory_code=record.factory_code,
            label_uid=label_uid,
            issued_at=record.scanned_at,
            issued_by=record.scanned_by,
        )
        db.add(label)
    label.payload = label.payload or None
    label.production_order_id = data.get("production_order_id")
    label.sales_order_id = data.get("sales_order_id")
    label.work_order_id = data.get("work_order_id")
    label.production_batch_id = data.get("production_batch_id")
    label.model_id = data.get("model_id")
    label.production_no = data.get("production_no")
    label.sales_order_no = data.get("sales_order_no")
    label.batch_no = _normalize_production_batch_no(data.get("batch_no"))
    label.model_code = data.get("model_code")
    label.operation_section = data.get("operation_section")
    label.operation_code = data.get("operation_code")
    label.operation_name = data.get("operation_name")
    label.sewing_flow_id = _to_int(raw_work.get("sewing_flow_id"))
    label.sewing_line_code = _to_text(raw_work.get("sewing_line_code"))
    label.sewing_line_name = _to_text(raw_work.get("sewing_line_name"))
    label.cutting_passport_id = _to_int(raw_work.get("cutting_passport_id"))
    label.cutting_passport_no = _to_text(raw_work.get("cutting_passport_no"))
    label.size = _to_text(raw_work.get("size"))
    label.copy_index = _to_int(raw_work.get("copy_index")) or 1
    label.quantity = data.get("quantity") or Decimal("0")
    label.rate_per_piece = data.get("rate_per_piece") or Decimal("0")
    label.currency = data.get("currency") or "UZS"
    label.status = "scanned"
    label.payroll_record_id = record.id
    label.last_scanned_at = record.scanned_at
    label.returned_at = None
    label.returned_by = None
    db.flush()


def _create_record_from_payload(
    db: DbSession,
    payload: PayrollRecordIn,
    *,
    current: User,
    period_id_override: int | None = None,
    audit_individual: bool = True,
) -> tuple[PayrollRecord, bool]:
    factory_code = selected_factory_code(current)
    data = _normalize_record_payload(payload)
    payload_period_id = payload.payroll_period_id or _to_int(_extra(payload, "payrollPeriodId"))
    if period_id_override is not None and data.get("payroll_period_id") is None:
        data["payroll_period_id"] = period_id_override
    else:
        data["payroll_period_id"] = payload_period_id

    if data.get("scan_uid"):
        existing = db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid == data["scan_uid"],
        ).first()
        if existing:
            if data.get("employee_id") and int(existing.employee_id) != int(data["employee_id"]):
                raise HTTPException(
                    409,
                    "This payroll work QR was already recorded for another employee; generate a separate payroll QR for another payable worker/unit",
                )
            return existing, False

    data = _validate_and_enrich_record(db, data, factory_code)
    existing = db.query(PayrollRecord).filter(
        PayrollRecord.dedupe_key == data["dedupe_key"],
        PayrollRecord.factory_code == factory_code,
    ).first()
    if existing:
        return existing, False

    period = _attach_period(db, data.get("payroll_period_id"), data["scanned_at"], factory_code)
    _assert_period_accepts_records(period, current)
    data["payroll_period_id"] = period.id if period else None

    record = PayrollRecord(
        factory_code=factory_code,
        payroll_period_id=data["payroll_period_id"],
        scan_uid=data["scan_uid"],
        original_scan_uid=data["scan_uid"],
        dedupe_key=data["dedupe_key"],
        employee_id=data["employee_id"],
        employee_user_id=data["employee_user_id"],
        production_order_id=data["production_order_id"],
        sales_order_id=data["sales_order_id"],
        work_order_id=data["work_order_id"],
        production_batch_id=data["production_batch_id"],
        model_id=data["model_id"],
        production_no=data["production_no"],
        sales_order_no=data["sales_order_no"],
        batch_no=data["batch_no"],
        model_code=data["model_code"],
        operation_section=data["operation_section"],
        operation_code=data["operation_code"],
        operation_name=data["operation_name"],
        quantity=data["quantity"],
        rate_per_piece=data["rate_per_piece"],
        currency=data["currency"],
        total_amount=data["total_amount"],
        scanned_by=current.id,
        scanned_at=data["scanned_at"],
        source=data["source"],
        raw_employee_json=data["raw_employee_json"],
        raw_work_json=data["raw_work_json"],
        status="recorded",
        notes=data["notes"],
    )
    db.add(record)
    db.flush()
    _mark_qr_label_scanned(db, record, data)
    if audit_individual:
        log_action(
            db,
            current,
            "create",
            "PayrollRecord",
            record.id,
            new_value={"employee_id": record.employee_id, "total_amount": record.total_amount, "scan_uid": record.scan_uid},
        )
    return record, True


def _filtered_record_query(
    db: DbSession,
    *,
    factory_code: str,
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = db.query(PayrollRecord).filter(PayrollRecord.factory_code == factory_code)
    if department_id is not None:
        qry = qry.join(Employee, Employee.id == PayrollRecord.employee_id).filter(Employee.department_id == department_id)
    if period_id is not None:
        qry = qry.filter(PayrollRecord.payroll_period_id == period_id)
    if employee_id is not None:
        qry = qry.filter(PayrollRecord.employee_id == employee_id)
    if date_from is not None:
        qry = qry.filter(PayrollRecord.scanned_at >= as_utc(date_from))
    if date_to is not None:
        qry = qry.filter(PayrollRecord.scanned_at <= as_utc(date_to))
    return qry


def _filtered_adjustment_query(
    db: DbSession,
    *,
    factory_code: str,
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = db.query(PayrollAdjustment).filter(PayrollAdjustment.factory_code == factory_code)
    if department_id is not None:
        qry = qry.join(Employee, Employee.id == PayrollAdjustment.employee_id).filter(Employee.department_id == department_id)
    if period_id is not None:
        qry = qry.filter(PayrollAdjustment.payroll_period_id == period_id)
    if employee_id is not None:
        qry = qry.filter(PayrollAdjustment.employee_id == employee_id)
    if date_from is not None:
        qry = qry.filter(PayrollAdjustment.created_at >= as_utc(date_from))
    if date_to is not None:
        qry = qry.filter(PayrollAdjustment.created_at <= as_utc(date_to))
    return qry


@router.get("/periods", response_model=list[PayrollPeriodOut])
def list_periods(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.approve", "payroll.pay", "*")),
    status: str | None = None,
):
    qry = db.query(PayrollPeriod).filter(PayrollPeriod.factory_code == selected_factory_code(current))
    if status:
        qry = qry.filter(PayrollPeriod.status == status)
    return qry.order_by(PayrollPeriod.start_date.desc(), PayrollPeriod.id.desc()).all()


@router.post("/periods", response_model=PayrollPeriodOut, status_code=201)
def create_period(
    payload: PayrollPeriodIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    if payload.status not in PERIOD_CREATE_STATUSES:
        raise HTTPException(400, "New payroll periods must be draft or open")
    _validate_period_dates(payload.start_date, payload.end_date)
    factory_code = selected_factory_code(current)
    period_no = payload.period_no.strip() if payload.period_no else _period_no_for(db, payload.start_date, factory_code)
    if db.query(PayrollPeriod.id).filter(
        PayrollPeriod.factory_code == factory_code,
        PayrollPeriod.period_no == period_no,
    ).first():
        raise HTTPException(400, "Payroll period number already exists")
    period = PayrollPeriod(
        factory_code=factory_code,
        period_no=period_no,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        created_by=current.id,
        notes=payload.notes,
    )
    db.add(period)
    db.flush()
    log_action(db, current, "create", "PayrollPeriod", period.id, new_value={"period_no": period.period_no})
    db.commit()
    db.refresh(period)
    return period


@router.patch("/periods/{period_id}", response_model=PayrollPeriodOut)
def update_period(
    period_id: int,
    payload: PayrollPeriodUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first()
    if not period:
        raise HTTPException(404, "Payroll period not found")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        next_status = changes["status"]
        if next_status not in PERIOD_STATUSES:
            raise HTTPException(400, "Invalid payroll period status")
        if next_status not in PERIOD_MANAGE_STATUS_TRANSITIONS.get(period.status, {period.status}):
            raise HTTPException(409, "Use the dedicated lock, approval, or payment action for this payroll status")
    start_date = changes.get("start_date", period.start_date)
    end_date = changes.get("end_date", period.end_date)
    _validate_period_dates(start_date, end_date)
    if changes.get("period_no"):
        exists = db.query(PayrollPeriod.id).filter(
            PayrollPeriod.factory_code == factory_code,
            PayrollPeriod.period_no == changes["period_no"],
            PayrollPeriod.id != period.id,
        ).first()
        if exists:
            raise HTTPException(400, "Payroll period number already exists")
    old = {key: getattr(period, key) for key in changes.keys() if hasattr(period, key)}
    for key, value in changes.items():
        setattr(period, key, value)
    log_action(db, current, "update", "PayrollPeriod", period.id, old_value=old, new_value=changes)
    db.commit()
    db.refresh(period)
    return period


@router.post("/periods/{period_id}/lock", response_model=PayrollPeriodOut)
def lock_period(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first()
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status in {"approved", "paid", "cancelled"}:
        raise HTTPException(409, f"Cannot lock a {period.status} payroll period")
    old_status = period.status
    period.status = "locked"
    log_action(db, current, "lock", "PayrollPeriod", period.id, old_value={"status": old_status}, new_value={"status": period.status})
    db.commit()
    db.refresh(period)
    return period


@router.post("/periods/{period_id}/approve", response_model=PayrollPeriodOut)
def approve_period(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.approve", "*")),
):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first()
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "locked":
        raise HTTPException(409, "Only locked payroll periods can be approved")
    old_status = period.status
    period.status = "approved"
    period.approved_by = current.id
    period.approved_at = utcnow()
    db.query(PayrollRecord).filter(
        PayrollRecord.factory_code == factory_code,
        PayrollRecord.payroll_period_id == period.id,
        PayrollRecord.status == "recorded",
    ).update({"status": "approved"}, synchronize_session=False)
    log_action(db, current, "approve", "PayrollPeriod", period.id, old_value={"status": old_status}, new_value={"status": period.status})
    db.commit()
    db.refresh(period)
    return period


@router.post("/periods/{period_id}/mark-paid", response_model=PayrollPeriodOut)
def mark_period_paid(
    period_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.pay", "*")),
):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first()
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "approved":
        raise HTTPException(409, "Only approved payroll periods can be marked paid")
    period.status = "paid"
    db.query(PayrollRecord).filter(
        PayrollRecord.factory_code == factory_code,
        PayrollRecord.payroll_period_id == period.id,
        PayrollRecord.status.in_(["recorded", "approved"]),
    ).update({"status": "paid"}, synchronize_session=False)
    log_action(db, current, "mark_paid", "PayrollPeriod", period.id, new_value={"status": period.status})
    db.commit()
    db.refresh(period)
    return period


@router.get("/records", response_model=list[PayrollRecordOut])
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
):
    qry = _filtered_record_query(
        db,
        factory_code=selected_factory_code(current),
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    if status == "active":
        qry = qry.filter(PayrollRecord.status != "voided")
    elif status in RECORD_STATUSES:
        qry = qry.filter(PayrollRecord.status == status)
    elif status:
        raise HTTPException(400, "Invalid payroll record status")
    rows = qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc()).limit(max(1, min(limit, 1000))).all()
    employees, departments = _load_employee_maps(db, {int(r.employee_id) for r in rows})
    return [_serialize_record(r, employees=employees, departments=departments) for r in rows]


def _serialize_qr_label(
    label: PayrollQrLabel,
    *,
    records: dict[int, PayrollRecord],
    employees: dict[int, Employee],
    departments: dict[int, Department],
) -> dict[str, Any]:
    record = records.get(int(label.payroll_record_id)) if label.payroll_record_id else None
    employee = employees.get(int(record.employee_id)) if record else None
    department = departments.get(int(employee.department_id)) if employee and employee.department_id else None
    return {
        "id": label.id,
        "factory_code": label.factory_code,
        "label_uid": label.label_uid,
        "qr_token": _work_qr_token(int(label.id)),
        "payload": label.payload,
        "production_order_id": label.production_order_id,
        "sales_order_id": label.sales_order_id,
        "work_order_id": label.work_order_id,
        "production_batch_id": label.production_batch_id,
        "model_id": label.model_id,
        "production_no": label.production_no,
        "sales_order_no": label.sales_order_no,
        "batch_no": _normalize_production_batch_no(label.batch_no),
        "model_code": label.model_code,
        "operation_section": label.operation_section,
        "operation_code": label.operation_code,
        "operation_name": label.operation_name,
        "sewing_flow_id": label.sewing_flow_id,
        "sewing_line_code": label.sewing_line_code,
        "sewing_line_name": label.sewing_line_name,
        "cutting_passport_id": label.cutting_passport_id,
        "cutting_passport_no": label.cutting_passport_no,
        "size": label.size,
        "copy_index": label.copy_index,
        "quantity": label.quantity,
        "rate_per_piece": label.rate_per_piece,
        "currency": label.currency,
        "status": label.status,
        "payroll_record_id": label.payroll_record_id,
        "employee_id": record.employee_id if record else None,
        "employee_name": employee.full_name if employee else None,
        "department_name": department.name if department else None,
        "payroll_status": record.status if record else None,
        "issued_at": label.issued_at,
        "last_scanned_at": label.last_scanned_at,
        "returned_at": label.returned_at,
        "return_count": label.return_count,
        "superseded_at": label.superseded_at,
        "superseded_by": label.superseded_by,
        "split_from_label_id": label.split_from_label_id,
    }


def _qr_label_maps(
    db: DbSession,
    labels: list[PayrollQrLabel],
) -> tuple[dict[int, PayrollRecord], dict[int, Employee], dict[int, Department]]:
    record_ids = {int(label.payroll_record_id) for label in labels if label.payroll_record_id}
    records = {
        int(record.id): record
        for record in (db.query(PayrollRecord).filter(PayrollRecord.id.in_(record_ids)).all() if record_ids else [])
    }
    employees, departments = _load_employee_maps(db, {int(record.employee_id) for record in records.values()})
    return records, employees, departments


def _order_qr_label_query(db: DbSession, order_no: str, factory_code: str):
    return db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == factory_code,
        PayrollQrLabel.status != "superseded",
        or_(
            PayrollQrLabel.sales_order_no == order_no,
            PayrollQrLabel.production_no == order_no,
        ),
    )


def _qr_size_sort_key(value: str) -> tuple[int, int, str]:
    normalized = value.strip().upper().replace(" ", "")
    garment_order = {
        "XXS": 10,
        "XS": 20,
        "S": 30,
        "M": 40,
        "L": 50,
        "XL": 60,
        "2XL": 70,
        "XXL": 70,
        "3XL": 80,
        "XXXL": 80,
        "4XL": 90,
        "5XL": 100,
    }
    if normalized in garment_order:
        return (0, garment_order[normalized], normalized)
    digits = "".join(char for char in normalized if char.isdigit())
    if digits:
        return (1, int(digits), normalized)
    if normalized == "N/A":
        return (3, 0, normalized)
    return (2, 0, normalized)


@router.get("/reports/order-qr-status/orders", response_model=list[OrderQrStatusOrderOption])
def order_qr_status_orders(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    search: str | None = None,
    limit: int = 50,
):
    qry = db.query(
        PayrollQrLabel.sales_order_no,
        PayrollQrLabel.production_no,
        PayrollQrLabel.model_code,
        func.count(PayrollQrLabel.id),
        func.max(PayrollQrLabel.issued_at),
    ).filter(
        PayrollQrLabel.factory_code == selected_factory_code(current),
        PayrollQrLabel.status != "superseded",
        or_(
            PayrollQrLabel.sales_order_no.isnot(None),
            PayrollQrLabel.production_no.isnot(None),
        ),
    )
    needle = (search or "").strip()
    if needle:
        pattern = f"%{needle}%"
        qry = qry.filter(or_(
            PayrollQrLabel.sales_order_no.ilike(pattern),
            PayrollQrLabel.production_no.ilike(pattern),
        ))
    rows = (
        qry.group_by(
            PayrollQrLabel.sales_order_no,
            PayrollQrLabel.production_no,
            PayrollQrLabel.model_code,
        )
        .order_by(func.max(PayrollQrLabel.issued_at).desc())
        .limit(500)
        .all()
    )
    grouped: dict[str, dict[str, Any]] = {}
    for sales_no, production_no, model_code, label_count, latest_at in rows:
        order_key = str(sales_no or production_no or "").strip()
        if not order_key:
            continue
        current = grouped.setdefault(order_key, {
            "order_no": order_key,
            "sales_order_nos": set(),
            "production_nos": set(),
            "model_codes": set(),
            "label_count": 0,
            "latest_at": latest_at,
        })
        if sales_no:
            current["sales_order_nos"].add(str(sales_no))
        if production_no:
            current["production_nos"].add(str(production_no))
        if model_code:
            current["model_codes"].add(str(model_code))
        current["label_count"] += int(label_count or 0)
        if latest_at and (not current["latest_at"] or latest_at > current["latest_at"]):
            current["latest_at"] = latest_at
    ordered = sorted(
        grouped.values(),
        key=lambda row: row["latest_at"].timestamp() if row["latest_at"] else 0,
        reverse=True,
    )
    safe_limit = max(1, min(limit, 100))
    return [
        {
            "order_no": row["order_no"],
            "sales_order_nos": sorted(row["sales_order_nos"]),
            "production_nos": sorted(row["production_nos"]),
            "model_codes": sorted(row["model_codes"]),
            "label_count": row["label_count"],
        }
        for row in ordered[:safe_limit]
    ]


@router.get("/reports/order-qr-status", response_model=OrderQrStatusOut)
def order_qr_status_report(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    order_no: str = "",
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    exact_order = order_no.strip()
    if not exact_order:
        raise HTTPException(400, "Order number is required")
    if status and status not in {"available", "scanned"}:
        raise HTTPException(400, "Invalid payroll QR status")

    all_labels = (
        _order_qr_label_query(db, exact_order, selected_factory_code(current))
        .order_by(
            PayrollQrLabel.operation_section.asc(),
            PayrollQrLabel.operation_name.asc(),
            PayrollQrLabel.operation_code.asc(),
            PayrollQrLabel.size.asc(),
            PayrollQrLabel.copy_index.asc(),
            PayrollQrLabel.id.asc(),
        )
        .all()
    )
    if not all_labels:
        raise HTTPException(404, "No payroll QR labels were found for this order")

    sizes = sorted({str(label.size or "N/A").strip() or "N/A" for label in all_labels}, key=_qr_size_sort_key)
    operation_groups: dict[tuple[str, str, str], list[PayrollQrLabel]] = {}
    for label in all_labels:
        operation_name = str(label.operation_name or label.operation_code or "Unspecified operation").strip()
        key = (
            str(label.operation_section or ""),
            str(label.operation_code or ""),
            operation_name,
        )
        operation_groups.setdefault(key, []).append(label)

    operations = []
    for (section, code, name), labels in operation_groups.items():
        cells = []
        for size in sizes:
            cell_labels = [label for label in labels if (str(label.size or "N/A").strip() or "N/A") == size]
            scanned = [label for label in cell_labels if label.status == "scanned"]
            available = [label for label in cell_labels if label.status == "available"]
            cells.append({
                "size": size,
                "issued_labels": len(cell_labels),
                "scanned_labels": len(scanned),
                "available_labels": len(available),
                "issued_quantity": sum((_to_decimal(label.quantity) for label in cell_labels), Decimal("0")),
                "scanned_quantity": sum((_to_decimal(label.quantity) for label in scanned), Decimal("0")),
                "available_quantity": sum((_to_decimal(label.quantity) for label in available), Decimal("0")),
            })
        scanned = [label for label in labels if label.status == "scanned"]
        available = [label for label in labels if label.status == "available"]
        operations.append({
            "operation_section": section or None,
            "operation_code": code or None,
            "operation_name": name,
            "cells": cells,
            "issued_labels": len(labels),
            "scanned_labels": len(scanned),
            "available_labels": len(available),
            "issued_quantity": sum((_to_decimal(label.quantity) for label in labels), Decimal("0")),
            "scanned_quantity": sum((_to_decimal(label.quantity) for label in scanned), Decimal("0")),
            "available_quantity": sum((_to_decimal(label.quantity) for label in available), Decimal("0")),
        })

    detail_qry = _order_qr_label_query(db, exact_order, selected_factory_code(current))
    if status:
        detail_qry = detail_qry.filter(PayrollQrLabel.status == status)
    total = detail_qry.count()
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    items = (
        detail_qry.order_by(PayrollQrLabel.issued_at.desc(), PayrollQrLabel.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )
    records, employees, departments = _qr_label_maps(db, items)
    scanned_labels = [label for label in all_labels if label.status == "scanned"]
    available_labels = [label for label in all_labels if label.status == "available"]
    return {
        "order_no": exact_order,
        "sales_order_nos": sorted({str(label.sales_order_no) for label in all_labels if label.sales_order_no}),
        "production_nos": sorted({str(label.production_no) for label in all_labels if label.production_no}),
        "model_codes": sorted({str(label.model_code) for label in all_labels if label.model_code}),
        "batch_nos": sorted({
            normalized
            for label in all_labels
            if (normalized := _normalize_production_batch_no(label.batch_no))
        }),
        "sizes": sizes,
        "operations": operations,
        "items": [
            _serialize_qr_label(label, records=records, employees=employees, departments=departments)
            for label in items
        ],
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "total_labels": len(all_labels),
        "scanned_labels": len(scanned_labels),
        "available_labels": len(available_labels),
        "total_quantity": sum((_to_decimal(label.quantity) for label in all_labels), Decimal("0")),
        "scanned_quantity": sum((_to_decimal(label.quantity) for label in scanned_labels), Decimal("0")),
        "available_quantity": sum((_to_decimal(label.quantity) for label in available_labels), Decimal("0")),
    }


def _sewing_report_base_query(db: DbSession, factory_code: str):
    return (
        db.query(PayrollRecord, Employee, PayrollQrLabel, Model, SewingFlow)
        .join(Employee, Employee.id == PayrollRecord.employee_id)
        .outerjoin(PayrollQrLabel, PayrollQrLabel.payroll_record_id == PayrollRecord.id)
        .outerjoin(Model, Model.id == PayrollRecord.model_id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(PayrollRecord.factory_code == factory_code)
    )


def _sewing_report_factory_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized not in {"MIL", "BST", "ECO"}:
        raise HTTPException(400, "Factory must be MIL, BST, or ECO")
    return normalized


def _sewing_report_options(db: DbSession, factory_code: str) -> dict[str, list[dict[str, str]]]:
    factory_code = _sewing_report_factory_code(factory_code)

    def bundle_factory_condition():
        if factory_code == "MIL":
            return or_(
                Bundle.sewing_factory_code.in_(("MIL", "SEW")),
                Bundle.sewing_factory_code.is_(None),
            )
        return Bundle.sewing_factory_code == factory_code

    routed_order_ids = db.query(Bundle.production_order_id).distinct()
    routed_model_ids = db.query(Bundle.model_id).distinct()
    if factory_code:
        routed_order_ids = routed_order_ids.filter(bundle_factory_condition())
        routed_model_ids = routed_model_ids.filter(bundle_factory_condition())

    employee_qry = (
        db.query(
            Employee.id,
            Employee.full_name,
            Employee.employee_no,
            Employee.position,
            Department.name,
        )
        .select_from(Employee)
        .outerjoin(Department, Department.id == Employee.department_id)
        .outerjoin(User, User.id == Employee.user_id)
        .filter(Employee.status == "active", Employee.factory_code == factory_code)
    )
    employees = employee_qry.order_by(Employee.full_name.asc(), Employee.id.asc()).all()

    operation_qry = (
        db.query(
            PayrollRecord.operation_code,
            PayrollRecord.operation_name,
            PayrollRecord.operation_section,
        )
        .select_from(PayrollRecord)
        .outerjoin(PayrollQrLabel, PayrollQrLabel.payroll_record_id == PayrollRecord.id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(
            PayrollRecord.factory_code == factory_code,
            or_(PayrollRecord.operation_code.isnot(None), PayrollRecord.operation_name.isnot(None)),
        )
    )
    operations = operation_qry.distinct().order_by(
        PayrollRecord.operation_name.asc(),
        PayrollRecord.operation_code.asc(),
    ).all()

    configured_operations: list[tuple[str | None, str | None, str | None]] = []
    production_model_query = db.query(Model.details_json)
    if factory_code:
        production_model_query = production_model_query.filter(Model.id.in_(routed_model_ids))
    else:
        production_model_query = production_model_query.filter(Model.id.in_(db.query(ProductionOrder.model_id).distinct()))
    production_model_details = production_model_query.all()
    for (details,) in production_model_details:
        for raw in filter_operation_rows(paid_operations_from_details(details), factory_code):
            if not isinstance(raw, dict) or raw.get("selected") is False:
                continue
            section = str(raw.get("section") or "sewing").strip().lower()
            if section != "sewing":
                continue
            code = str(raw.get("code") or "").strip().upper() or None
            name = str(raw.get("name") or raw.get("operation_name") or "").strip() or None
            if code or name:
                configured_operations.append((code, name, section))
    line_qry = (
        db.query(
            PayrollQrLabel.sewing_line_code,
            PayrollQrLabel.sewing_line_name,
            SewingFlow.code,
            SewingFlow.name,
            SewingFlow.factory_code,
        )
        .select_from(PayrollQrLabel)
        .join(PayrollRecord, PayrollRecord.id == PayrollQrLabel.payroll_record_id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(
            PayrollQrLabel.factory_code == factory_code,
            or_(
                PayrollQrLabel.sewing_line_code.isnot(None),
                PayrollQrLabel.sewing_line_name.isnot(None),
                SewingFlow.code.isnot(None),
                SewingFlow.name.isnot(None),
            ),
        )
    )
    lines = line_qry.distinct().order_by(
        PayrollQrLabel.sewing_line_code.asc(),
        PayrollQrLabel.sewing_line_name.asc(),
    ).all()

    configured_line_qry = (
        db.query(SewingFlow.code, SewingFlow.name, SewingFlow.factory_code)
        .filter(SewingFlow.is_active.is_(True))
    )
    if factory_code:
        configured_line_qry = configured_line_qry.filter(SewingFlow.factory_code == factory_code)
    configured_lines = configured_line_qry.order_by(SewingFlow.code.asc(), SewingFlow.name.asc()).all()

    model_qry = (
        db.query(PayrollRecord.model_code, Model.name, Model.product_type)
        .select_from(PayrollRecord)
        .outerjoin(PayrollQrLabel, PayrollQrLabel.payroll_record_id == PayrollRecord.id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .outerjoin(Model, Model.id == PayrollRecord.model_id)
        .filter(PayrollRecord.factory_code == factory_code, PayrollRecord.model_code.isnot(None))
    )
    models = model_qry.distinct().order_by(PayrollRecord.model_code.asc()).all()

    production_model_qry = (
        db.query(Model.code, Model.name, Model.product_type)
        .join(ProductionOrder, ProductionOrder.model_id == Model.id)
    )
    if factory_code:
        production_model_qry = production_model_qry.filter(ProductionOrder.id.in_(routed_order_ids))
    production_models = production_model_qry.distinct().order_by(Model.code.asc()).all()

    order_qry = (
        db.query(PayrollRecord.production_no, PayrollRecord.sales_order_no, PayrollRecord.model_code)
        .select_from(PayrollRecord)
        .outerjoin(PayrollQrLabel, PayrollQrLabel.payroll_record_id == PayrollRecord.id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(
            PayrollRecord.factory_code == factory_code,
            or_(PayrollRecord.production_no.isnot(None), PayrollRecord.sales_order_no.isnot(None)),
        )
    )
    orders = order_qry.distinct().order_by(
        PayrollRecord.production_no.asc(),
        PayrollRecord.sales_order_no.asc(),
    ).all()

    production_order_qry = (
        db.query(ProductionOrder.production_no, SalesOrder.order_no, Model.code)
        .select_from(ProductionOrder)
        .outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
        .join(Model, Model.id == ProductionOrder.model_id)
    )
    if factory_code:
        production_order_qry = production_order_qry.filter(ProductionOrder.id.in_(routed_order_ids))
    production_orders = production_order_qry.order_by(ProductionOrder.production_no.asc()).all()

    cutting_qry = (
        db.query(
            PayrollQrLabel.cutting_passport_no,
            PayrollRecord.batch_no,
            PayrollRecord.production_no,
            PayrollRecord.model_code,
        )
        .select_from(PayrollQrLabel)
        .join(PayrollRecord, PayrollRecord.id == PayrollQrLabel.payroll_record_id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(
            PayrollQrLabel.factory_code == factory_code,
            or_(PayrollQrLabel.cutting_passport_no.isnot(None), PayrollRecord.batch_no.isnot(None)),
        )
    )
    cutting_references = cutting_qry.distinct().order_by(
        PayrollQrLabel.cutting_passport_no.asc(),
        PayrollRecord.batch_no.asc(),
    ).all()

    production_batch_qry = (
        db.query(ProductionBatch.batch_no, ProductionOrder.production_no, Model.code)
        .select_from(ProductionBatch)
        .join(ProductionOrder, ProductionOrder.id == ProductionBatch.production_order_id)
        .join(Model, Model.id == ProductionOrder.model_id)
    )
    if factory_code:
        production_batch_qry = production_batch_qry.filter(ProductionOrder.id.in_(routed_order_ids))
    production_batches = production_batch_qry.order_by(ProductionBatch.batch_no.asc()).all()

    size_qry = (
        db.query(PayrollQrLabel.size)
        .select_from(PayrollQrLabel)
        .join(PayrollRecord, PayrollRecord.id == PayrollQrLabel.payroll_record_id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(PayrollQrLabel.factory_code == factory_code, PayrollQrLabel.size.isnot(None))
    )
    sizes = size_qry.distinct().all()
    bundle_size_qry = db.query(Bundle.size).filter(Bundle.size.isnot(None))
    if factory_code:
        bundle_size_qry = bundle_size_qry.filter(bundle_factory_condition())
    production_sizes = bundle_size_qry.distinct().all()

    def make_label(*parts: Any) -> str:
        return " | ".join(str(part).strip() for part in parts if part is not None and str(part).strip())

    def unique_options(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        by_value: dict[str, dict[str, str]] = {}
        for row in rows:
            if row["value"] and row["value"] not in by_value:
                by_value[row["value"]] = row
        return list(by_value.values())

    order_option_rows: list[dict[str, str]] = []
    for production_no, sales_order_no, model_code in [*orders, *production_orders]:
        if production_no:
            order_option_rows.append({
                "value": str(production_no),
                "label": make_label(production_no, sales_order_no, model_code),
            })
        if sales_order_no and sales_order_no != production_no:
            order_option_rows.append({
                "value": str(sales_order_no),
                "label": make_label(sales_order_no, production_no, model_code),
            })
    order_options = unique_options(order_option_rows)
    cutting_options: list[dict[str, str]] = []
    for passport_no, batch_no, production_no, model_code in cutting_references:
        context = make_label(passport_no, batch_no, production_no, model_code)
        if passport_no:
            cutting_options.append({"value": str(passport_no), "label": context})
        if batch_no and batch_no != passport_no:
            cutting_options.append({
                "value": str(batch_no),
                "label": make_label(batch_no, passport_no, production_no, model_code),
            })
    for batch_no, production_no, model_code in production_batches:
        if batch_no:
            cutting_options.append({
                "value": str(batch_no),
                "label": make_label(batch_no, production_no, model_code),
            })

    return {
        "employees": [
            {
                "value": str(employee_id),
                "label": make_label(full_name, employee_no or employee_id, position, department_name),
            }
            for employee_id, full_name, employee_no, position, department_name in employees
        ],
        "operations": unique_options([
            {
                "value": str(code or name),
                "label": make_label(name or code, code if code and code != name else None, section),
            }
            for code, name, section in [*operations, *configured_operations]
        ]),
        "sewing_lines": unique_options([
            {
                "value": str(label_code or flow_code or label_name or flow_name),
                "label": make_label(label_code or flow_code, label_name or flow_name, factory_code),
            }
            for label_code, label_name, flow_code, flow_name, factory_code in lines
        ] + [
            {
                "value": str(code or name),
                "label": make_label(code, name, factory_code),
            }
            for code, name, factory_code in configured_lines
            if code or name
        ]),
        "models": unique_options([
            {"value": str(code), "label": make_label(code, name, product_type)}
            for code, name, product_type in [*models, *production_models]
        ]),
        "orders": order_options,
        "cutting_references": unique_options(cutting_options),
        "sizes": [
            {"value": str(size), "label": str(size)}
            for (size,) in sorted(
                {*sizes, *production_sizes},
                key=lambda row: _qr_size_sort_key(str(row[0])),
            )
        ],
    }


@router.get("/reports/sewing-production/options", response_model=SewingProductionReportOptions)
def sewing_production_report_options(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    factory_code: str | None = None,
):
    scoped_factory = selected_factory_code(current)
    if factory_code:
        require_factory_access(current, factory_code)
    return _sewing_report_options(db, scoped_factory)


def _filtered_sewing_production_report_query(
    db: DbSession,
    *,
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
):
    allowed_statuses = {"active", "all", *RECORD_STATUSES}
    if status not in allowed_statuses:
        raise HTTPException(400, "Invalid payroll report status")
    factory_code = _sewing_report_factory_code(factory_code)

    if not factory_code:
        raise HTTPException(400, "Factory scope is required")
    qry = _sewing_report_base_query(db, factory_code)
    if status == "active":
        qry = qry.filter(PayrollRecord.status != "voided")
    elif status != "all":
        qry = qry.filter(PayrollRecord.status == status)
    if date_from:
        qry = qry.filter(PayrollRecord.scanned_at >= as_utc(date_from))
    if date_to:
        qry = qry.filter(PayrollRecord.scanned_at <= as_utc(date_to))
    if employee_id:
        qry = qry.filter(PayrollRecord.employee_id == employee_id)
    if order_no and order_no.strip():
        pattern = f"%{order_no.strip()}%"
        qry = qry.filter(or_(PayrollRecord.production_no.ilike(pattern), PayrollRecord.sales_order_no.ilike(pattern)))
    if cutting_reference and cutting_reference.strip():
        pattern = f"%{cutting_reference.strip()}%"
        qry = qry.filter(or_(PayrollQrLabel.cutting_passport_no.ilike(pattern), PayrollRecord.batch_no.ilike(pattern)))
    if model_code and model_code.strip():
        qry = qry.filter(normalized_model_code_column(PayrollRecord.model_code).ilike(normalized_model_code_pattern(model_code)))
    if sewing_flow_id:
        qry = qry.filter(PayrollQrLabel.sewing_flow_id == sewing_flow_id)
    if sewing_line and sewing_line.strip():
        pattern = f"%{sewing_line.strip()}%"
        qry = qry.filter(or_(
            PayrollQrLabel.sewing_line_code.ilike(pattern),
            PayrollQrLabel.sewing_line_name.ilike(pattern),
            SewingFlow.code.ilike(pattern),
            SewingFlow.name.ilike(pattern),
        ))
    if operation and operation.strip():
        qry = qry.filter(or_(PayrollRecord.operation_code == operation.strip(), PayrollRecord.operation_name == operation.strip()))
    if barcode and barcode.strip():
        pattern = f"%{barcode.strip()}%"
        qry = qry.filter(or_(
            PayrollQrLabel.label_uid.ilike(pattern),
            PayrollRecord.scan_uid.ilike(pattern),
            PayrollRecord.original_scan_uid.ilike(pattern),
        ))
    if size and size.strip():
        qry = qry.filter(PayrollQrLabel.size == size.strip())
    return qry, factory_code


def _sewing_production_report_items(rows) -> list[dict]:
    items = []
    for record, employee, label, model, flow in rows:
        raw_work = record.raw_work_json if isinstance(record.raw_work_json, dict) else {}
        line_code = label.sewing_line_code if label else raw_work.get("sewing_line_code")
        line_name = label.sewing_line_name if label else raw_work.get("sewing_line_name")
        cutting_no = label.cutting_passport_no if label else raw_work.get("cutting_passport_no")
        items.append({
            "id": record.id,
            "scanned_at": record.scanned_at,
            "employee_id": record.employee_id,
            "employee_no": employee.employee_no,
            "employee_name": employee.full_name,
            "barcode": _work_qr_token(int(label.id)) if label else str(record.original_scan_uid or record.scan_uid or record.id),
            "sewing_line_code": line_code or (flow.code if flow else None),
            "sewing_line_name": line_name or (flow.name if flow else None),
            "cutting_reference": cutting_no or _normalize_production_batch_no(record.batch_no),
            "production_no": record.production_no,
            "sales_order_no": record.sales_order_no,
            "batch_no": _normalize_production_batch_no(record.batch_no),
            "model_code": record.model_code,
            "product_name": (model.product_type or model.name) if model else None,
            "operation_code": record.operation_code,
            "operation_name": record.operation_name,
            "size": label.size if label else raw_work.get("size"),
            "quantity": record.quantity,
            "rate_per_piece": record.rate_per_piece,
            "total_amount": record.total_amount,
            "currency": record.currency,
            "status": record.status,
            "factory_code": record.factory_code,
        })
    return items


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
    limit: int = 100,
    offset: int = 0,
):
    scoped_factory = selected_factory_code(current)
    if factory_code:
        require_factory_access(current, factory_code)
    qry, factory_code = _filtered_sewing_production_report_query(
        db,
        date_from=date_from,
        date_to=date_to,
        employee_id=employee_id,
        order_no=order_no,
        cutting_reference=cutting_reference,
        model_code=model_code,
        sewing_flow_id=sewing_flow_id,
        sewing_line=sewing_line,
        operation=operation,
        barcode=barcode,
        size=size,
        factory_code=scoped_factory,
        status=status,
    )

    total = qry.count()
    aggregate = qry.with_entities(
        func.coalesce(func.sum(PayrollRecord.quantity), 0),
        func.coalesce(func.sum(PayrollRecord.total_amount), 0),
    ).one()
    currencies = {
        str(value)
        for (value,) in qry.with_entities(PayrollRecord.currency).distinct().all()
        if value
    }
    report_currency = next(iter(currencies)) if len(currencies) == 1 else ("MIXED" if currencies else "UZS")
    safe_limit = max(1, min(limit, 5000))
    safe_offset = max(0, offset)
    rows = (
        qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )

    items = _sewing_production_report_items(rows)
    return {
        "items": items,
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "total_quantity": aggregate[0],
        "total_amount": aggregate[1],
        "currency": report_currency,
        "options": _sewing_report_options(db, factory_code),
    }


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
):
    scoped_factory = selected_factory_code(current)
    if factory_code:
        require_factory_access(current, factory_code)
    qry, _ = _filtered_sewing_production_report_query(
        db,
        date_from=date_from,
        date_to=date_to,
        employee_id=employee_id,
        order_no=order_no,
        cutting_reference=cutting_reference,
        model_code=model_code,
        sewing_flow_id=sewing_flow_id,
        sewing_line=sewing_line,
        operation=operation,
        barcode=barcode,
        size=size,
        factory_code=scoped_factory,
        status=status,
    )
    rows = qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc()).all()
    items = _sewing_production_report_items(rows)
    currencies = {str(item["currency"]) for item in items if item.get("currency")}
    report_currency = next(iter(currencies)) if len(currencies) == 1 else ("MIXED" if currencies else "UZS")
    generated_at = datetime.now(ZoneInfo("Asia/Tashkent"))
    workbook = build_sewing_production_report_xlsx(
        items,
        date_from=date_from,
        date_to=date_to,
        generated_label=generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        lang=lang,
        currency=report_currency,
    )
    filename = f"sewing-production-report-{generated_at.strftime('%Y-%m-%d')}.xlsx"
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/qr-labels/issue", response_model=PayrollQrLabelsIssueOut)
def issue_qr_labels(
    payload: PayrollQrLabelsIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    if not payload.labels:
        raise HTTPException(400, "At least one payroll QR label is required")
    issued_at = utcnow()
    factory_code = selected_factory_code(current)
    issued_ids: list[int] = []
    created_ids: list[int] = []
    existing_count = 0
    issued_labels: list[dict[str, str]] = []
    for row in payload.labels:
        if row.sewing_flow_id is not None:
            flow = db.query(SewingFlow).filter(
                SewingFlow.id == row.sewing_flow_id,
                SewingFlow.factory_code == factory_code,
            ).first()
            if not flow:
                raise HTTPException(404, "Sewing line was not found in this factory")
        work_order = db.get(WorkOrder, row.work_order_id) if row.work_order_id is not None else None
        if row.work_order_id is not None and not work_order:
            raise HTTPException(404, "Work order not found")
        if work_order:
            require_work_order_factory(db, work_order, factory_code)
            if row.production_order_id is not None and int(work_order.production_order_id) != int(row.production_order_id):
                raise HTTPException(400, "Work order does not belong to the production order")
        if row.production_order_id is not None:
            require_production_order_factory(db, int(row.production_order_id), factory_code)
        label_uid = row.label_uid.strip()
        if not label_uid or len(label_uid) > 128:
            raise HTTPException(400, "Invalid payroll QR label identifier")
        label = db.query(PayrollQrLabel).filter(
            PayrollQrLabel.factory_code == factory_code,
            PayrollQrLabel.label_uid == label_uid,
        ).first()
        is_new = label is None
        if is_new:
            label = PayrollQrLabel(factory_code=factory_code, label_uid=label_uid)
            db.add(label)
            values = row.model_dump(exclude={"label_uid"})
            for key, value in values.items():
                setattr(label, key, value)
            label.batch_no = _normalize_production_batch_no(row.batch_no)
            label.label_uid = label_uid
            label.currency = (row.currency or "UZS").upper()[:8]
            label.copy_index = max(1, int(row.copy_index or 1))
            label.quantity = _to_decimal(row.quantity)
            label.rate_per_piece = _to_decimal(row.rate_per_piece)
            label.issued_by = current.id
            label.issued_at = issued_at
        else:
            existing_count += 1
        active_record = db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid == label_uid,
        ).first()
        if active_record:
            label.status = "scanned"
            label.payroll_record_id = active_record.id
            label.last_scanned_at = active_record.scanned_at
        elif is_new:
            label.status = "available"
            label.payroll_record_id = None
        db.flush()
        issued_ids.append(int(label.id))
        if is_new:
            created_ids.append(int(label.id))
        issued_labels.append({"label_uid": label.label_uid, "qr_token": _work_qr_token(int(label.id))})
    if created_ids:
        log_action(
            db,
            current,
            "issue",
            "PayrollQrLabel",
            created_ids[0],
            new_value={"count": len(created_ids), "label_ids": created_ids[:100]},
        )
    db.commit()
    return {
        "issued_count": len(issued_ids),
        "created_count": len(created_ids),
        "existing_count": existing_count,
        "labels": issued_labels,
    }


def _employee_scan_payload(employee: Employee, *, badge_id: str, source: str, db: DbSession) -> dict[str, Any]:
    department = db.get(Department, employee.department_id) if employee.department_id else None
    department_name = None
    if department:
        department_name = f"{department.code} - {department.name}" if department.code else department.name
    return {
        "type": "employee_payroll",
        "source": source,
        "badge_id": badge_id,
        "employee_id": employee.id,
        "employee_no": employee.employee_no,
        "user_id": employee.user_id,
        "employee_name": employee.full_name,
        "department_id": employee.department_id,
        "department_name": department_name,
        "position": employee.position,
        "status": employee.status,
    }


@router.get("/employees/resolve")
def resolve_employee_number(
    employee_no: str,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    normalized = employee_no.strip()
    if not normalized or len(normalized) > 32:
        raise HTTPException(400, "Employee number must contain between 1 and 32 characters")

    employee = (
        db.query(Employee)
        .filter(
            Employee.factory_code == selected_factory_code(current),
            func.lower(func.trim(Employee.employee_no)) == normalized.lower(),
        )
        .one_or_none()
    )
    if not employee and normalized.upper().startswith("EMP-") and normalized[4:].isdigit():
        employee = db.query(Employee).filter(
            Employee.id == int(normalized[4:]),
            Employee.factory_code == selected_factory_code(current),
        ).first()
    if not employee:
        raise HTTPException(404, "Payroll employee number was not found")
    return _employee_scan_payload(
        employee,
        badge_id=normalized,
        source="milana_erp_employee_no",
        db=db,
    )


@router.get("/qr/resolve/{token}")
def resolve_qr_token(
    token: str,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    normalized = token.strip()
    if len(normalized) != PAYROLL_QR_TOKEN_LENGTH or not normalized.isdigit():
        raise HTTPException(400, "Payroll QR token must contain exactly 9 digits")

    record_id = int(normalized[1:])
    factory_code = selected_factory_code(current)
    if normalized.startswith(PAYROLL_EMPLOYEE_TOKEN_PREFIX):
        employee = db.query(Employee).filter(
            Employee.id == record_id,
            Employee.factory_code == factory_code,
        ).first()
        if not employee:
            raise HTTPException(404, "Payroll employee QR was not found")
        return _employee_scan_payload(
            employee,
            badge_id=normalized,
            source="milana_erp_token",
            db=db,
        )

    if normalized.startswith(PAYROLL_WORK_TOKEN_PREFIX):
        label = db.query(PayrollQrLabel).filter(
            PayrollQrLabel.id == record_id,
            PayrollQrLabel.factory_code == factory_code,
        ).first()
        if not label:
            raise HTTPException(404, "Payroll work QR was not found")
        if label.status == "superseded":
            raise HTTPException(409, "This payroll QR was replaced by split labels and can no longer be scanned")
        return {
            "type": "process_payroll",
            "source": "milana_erp_token",
            "label_id": label.label_uid,
            "production_order_id": label.production_order_id,
            "production_no": label.production_no,
            "sales_order_id": label.sales_order_id,
            "sales_order_no": label.sales_order_no,
            "work_order_id": label.work_order_id,
            "batch_id": label.production_batch_id,
            "batch_no": _normalize_production_batch_no(label.batch_no),
            "model_id": label.model_id,
            "model_code": label.model_code,
            "size": label.size,
            "operation_section": label.operation_section,
            "operation_code": label.operation_code,
            "operation_name": label.operation_name,
            "quantity": label.quantity,
            "rate_per_piece": label.rate_per_piece,
            "currency": label.currency,
            "payroll_unit": "piece",
            "copy_index": label.copy_index,
            "sewing_flow_id": label.sewing_flow_id,
            "sewing_line_code": label.sewing_line_code,
            "sewing_line_name": label.sewing_line_name,
            "cutting_passport_id": label.cutting_passport_id,
            "cutting_passport_no": label.cutting_passport_no,
            "label_status": label.status,
        }

    raise HTTPException(400, "Unknown payroll QR token type")


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
    if status and status not in {"available", "scanned", "superseded"}:
        raise HTTPException(400, "Invalid payroll QR status")
    qry = (
        db.query(PayrollQrLabel)
        .outerjoin(PayrollRecord, PayrollRecord.id == PayrollQrLabel.payroll_record_id)
        .outerjoin(Employee, Employee.id == PayrollRecord.employee_id)
        .filter(PayrollQrLabel.factory_code == selected_factory_code(current))
    )
    text_query = (search or "").strip()
    if text_query:
        pattern = f"%{text_query}%"
        model_code_pattern = normalized_model_code_pattern(text_query)
        search_filters = [
            PayrollQrLabel.label_uid.ilike(pattern),
            PayrollQrLabel.sales_order_no.ilike(pattern),
            PayrollQrLabel.production_no.ilike(pattern),
            PayrollQrLabel.batch_no.ilike(pattern),
            normalized_model_code_column(PayrollQrLabel.model_code).ilike(model_code_pattern),
            PayrollQrLabel.operation_code.ilike(pattern),
            PayrollQrLabel.operation_name.ilike(pattern),
            PayrollQrLabel.sewing_line_code.ilike(pattern),
            PayrollQrLabel.sewing_line_name.ilike(pattern),
            PayrollQrLabel.cutting_passport_no.ilike(pattern),
            Employee.full_name.ilike(pattern),
        ]
        token_label_id = _work_label_id_from_token(text_query)
        if token_label_id is not None:
            search_filters.append(PayrollQrLabel.id == token_label_id)
        qry = qry.filter(or_(*search_filters))
    exact_order = (order_no or "").strip()
    if exact_order:
        qry = qry.filter(or_(
            PayrollQrLabel.sales_order_no == exact_order,
            PayrollQrLabel.production_no == exact_order,
        ))
    if production_order_id is not None:
        qry = qry.filter(PayrollQrLabel.production_order_id == production_order_id)
    available_count = qry.filter(PayrollQrLabel.status == "available").count()
    scanned_count = qry.filter(PayrollQrLabel.status == "scanned").count()
    if status:
        qry = qry.filter(PayrollQrLabel.status == status)
    elif not include_superseded:
        qry = qry.filter(PayrollQrLabel.status != "superseded")
    total = qry.count()
    labels = (
        qry.order_by(PayrollQrLabel.issued_at.desc(), PayrollQrLabel.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 5000)))
        .all()
    )
    records, employees, departments = _qr_label_maps(db, labels)
    return {
        "items": [
            _serialize_qr_label(label, records=records, employees=employees, departments=departments)
            for label in labels
        ],
        "total": total,
        "available_count": available_count,
        "scanned_count": scanned_count,
    }


def _assert_qr_label_never_scanned(db: DbSession, label: PayrollQrLabel) -> None:
    if (
        label.status != "available"
        or label.payroll_record_id is not None
        or label.last_scanned_at is not None
        or int(label.return_count or 0) > 0
    ):
        raise HTTPException(409, "Only never-scanned payroll QR labels can be edited or split")
    historical_record = (
        db.query(PayrollRecord.id)
        .filter(
            PayrollRecord.factory_code == label.factory_code,
            or_(
                PayrollRecord.scan_uid == label.label_uid,
                PayrollRecord.original_scan_uid == label.label_uid,
            ),
        )
        .first()
    )
    if historical_record:
        raise HTTPException(409, "Payroll QR labels with payroll history cannot be edited or split")


def _corrected_label_values(payload: PayrollQrLabelEditIn) -> tuple[str, Decimal]:
    operation_name = payload.operation_name.strip()
    if not operation_name:
        raise HTTPException(400, "Payroll QR operation name is required")
    rate = _to_decimal(payload.rate_per_piece)
    if rate < 0:
        raise HTTPException(400, "Payroll QR rate cannot be negative")
    return operation_name, rate


@router.patch("/qr-labels/{label_id}", response_model=PayrollQrLabelOut)
def edit_qr_label(
    label_id: int,
    payload: PayrollQrLabelEditIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    label = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id == label_id,
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .one_or_none()
    )
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    _assert_qr_label_never_scanned(db, label)
    operation_name, rate = _corrected_label_values(payload)
    old_value = {
        "operation_name": label.operation_name,
        "rate_per_piece": str(label.rate_per_piece),
        "qr_token": _work_qr_token(int(label.id)),
    }
    label.operation_name = operation_name
    label.rate_per_piece = rate
    label.payload = None
    log_action(
        db,
        current,
        "edit_unscanned_qr",
        "PayrollQrLabel",
        int(label.id),
        old_value=old_value,
        new_value={
            "operation_name": operation_name,
            "rate_per_piece": str(rate),
            "qr_token": _work_qr_token(int(label.id)),
        },
    )
    db.commit()
    db.refresh(label)
    return _serialize_qr_label(label, records={}, employees={}, departments={})


@router.post("/qr-labels/{label_id}/split", response_model=PayrollQrLabelSplitOut)
def split_qr_label(
    label_id: int,
    payload: PayrollQrLabelSplitIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    label = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id == label_id,
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .one_or_none()
    )
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    _assert_qr_label_never_scanned(db, label)
    operation_name, rate = _corrected_label_values(payload)
    quantities = [int(quantity) for quantity in payload.quantities]
    if any(quantity <= 0 for quantity in quantities):
        raise HTTPException(400, "Every split quantity must be a positive whole number")
    original_quantity = _to_decimal(label.quantity)
    if sum(quantities) != original_quantity:
        raise HTTPException(409, "Split quantities must equal the original payroll QR quantity")

    copied_fields = {
        "production_order_id": label.production_order_id,
        "sales_order_id": label.sales_order_id,
        "work_order_id": label.work_order_id,
        "production_batch_id": label.production_batch_id,
        "model_id": label.model_id,
        "production_no": label.production_no,
        "sales_order_no": label.sales_order_no,
        "batch_no": label.batch_no,
        "model_code": label.model_code,
        "operation_section": label.operation_section,
        "operation_code": label.operation_code,
        "operation_name": operation_name,
        "sewing_flow_id": label.sewing_flow_id,
        "sewing_line_code": label.sewing_line_code,
        "sewing_line_name": label.sewing_line_name,
        "cutting_passport_id": label.cutting_passport_id,
        "cutting_passport_no": label.cutting_passport_no,
        "size": label.size,
        "rate_per_piece": rate,
        "currency": label.currency,
        "status": "available",
        "issued_by": current.id,
        "issued_at": utcnow(),
        "split_from_label_id": int(label.id),
    }
    children: list[PayrollQrLabel] = []
    for index, quantity in enumerate(quantities):
        child = PayrollQrLabel(
            factory_code=label.factory_code,
            label_uid=f"OERP-SPLIT-{uuid4().hex.upper()}",
            copy_index=max(1, int(label.copy_index or 1)) + index,
            quantity=Decimal(quantity),
            **copied_fields,
        )
        db.add(child)
        children.append(child)

    old_value = {
        "label_uid": label.label_uid,
        "qr_token": _work_qr_token(int(label.id)),
        "operation_name": label.operation_name,
        "quantity": str(label.quantity),
        "rate_per_piece": str(label.rate_per_piece),
    }
    label.status = "superseded"
    label.superseded_at = utcnow()
    label.superseded_by = current.id
    label.payroll_record_id = None
    db.flush()
    new_value = {
        "operation_name": operation_name,
        "rate_per_piece": str(rate),
        "quantities": quantities,
        "child_label_ids": [int(child.id) for child in children],
        "child_qr_tokens": [_work_qr_token(int(child.id)) for child in children],
    }
    log_action(
        db,
        current,
        "split_unscanned_qr",
        "PayrollQrLabel",
        int(label.id),
        old_value=old_value,
        new_value=new_value,
    )
    db.commit()
    for child in children:
        db.refresh(child)
    return {
        "superseded_label_id": int(label.id),
        "labels": [
            _serialize_qr_label(child, records={}, employees={}, departments={})
            for child in children
        ],
    }


@router.post("/qr-labels/delete-batch", response_model=PayrollQrLabelBatchDeleteOut)
def delete_qr_label_batch(
    payload: PayrollQrLabelBatchDeleteIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    label_ids = sorted({int(label_id) for label_id in payload.label_ids if int(label_id) > 0})
    if not label_ids:
        raise HTTPException(400, "At least one payroll QR label is required")

    labels = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id.in_(label_ids),
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .all()
    )
    if len(labels) != len(label_ids):
        raise HTTPException(404, "One or more payroll QR labels were not found")

    requested_size = payload.size.strip()
    actual_sizes = {str(label.size or "-").strip() or "-" for label in labels}
    if actual_sizes != {requested_size}:
        raise HTTPException(409, "Payroll QR labels must belong to the same requested size")

    order_keys = {
        (
            label.production_order_id,
            str(label.production_no or "").strip(),
            str(label.sales_order_no or "").strip(),
        )
        for label in labels
    }
    if len(order_keys) != 1:
        raise HTTPException(409, "Payroll QR labels must belong to the same order")

    if any(
        label.status != "available"
        or label.payroll_record_id is not None
        or label.last_scanned_at is not None
        or int(label.return_count or 0) > 0
        for label in labels
    ):
        raise HTTPException(409, "Only never-scanned payroll QR labels can be deleted")

    label_uids = [label.label_uid for label in labels]
    historical_record = (
        db.query(PayrollRecord.id)
        .filter(
            PayrollRecord.factory_code == selected_factory_code(current),
            or_(
                PayrollRecord.scan_uid.in_(label_uids),
                PayrollRecord.original_scan_uid.in_(label_uids),
            ),
        )
        .first()
    )
    if historical_record:
        raise HTTPException(409, "Payroll QR labels with payroll history cannot be deleted")

    audit_label = min(labels, key=lambda label: int(label.id))
    audit_value = {
        "size": requested_size,
        "count": len(labels),
        "label_ids": label_ids[:100],
        "production_order_id": audit_label.production_order_id,
        "production_no": audit_label.production_no,
        "sales_order_no": audit_label.sales_order_no,
    }
    log_action(
        db,
        current,
        "delete_unscanned_batch",
        "PayrollQrLabel",
        int(audit_label.id),
        old_value=audit_value,
    )
    for label in labels:
        db.delete(label)
    db.commit()
    return {"deleted_count": len(labels), "size": requested_size}


@router.post("/qr-labels/{label_id}/return", response_model=PayrollQrLabelOut)
def return_qr_label(
    label_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    label = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.id == label_id,
        PayrollQrLabel.factory_code == factory_code,
    ).first()
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    record = db.query(PayrollRecord).filter(
        PayrollRecord.id == label.payroll_record_id,
        PayrollRecord.factory_code == factory_code,
    ).first() if label.payroll_record_id else None
    if not record:
        record = db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid == label.label_uid,
        ).first()
    if not record:
        raise HTTPException(409, "This payroll QR is not assigned to an employee")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll QR records can only be returned by an admin")
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == record.payroll_period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first() if record.payroll_period_id else None
    if period and period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")

    previous = {
        "payroll_record_id": record.id,
        "employee_id": record.employee_id,
        "status": record.status,
        "scan_uid": record.scan_uid,
    }
    original_uid = record.original_scan_uid or record.scan_uid or label.label_uid
    record.original_scan_uid = original_uid
    record.scan_uid = None
    record.status = "voided"
    label.status = "available"
    label.payroll_record_id = None
    label.returned_at = utcnow()
    label.returned_by = current.id
    label.return_count = int(label.return_count or 0) + 1
    log_action(
        db,
        current,
        "return_qr",
        "PayrollQrLabel",
        label.id,
        old_value=previous,
        new_value={"status": "available", "return_count": label.return_count},
    )
    db.commit()
    db.refresh(label)
    return _serialize_qr_label(label, records={}, employees={}, departments={})


@router.post("/records", response_model=PayrollRecordOut, status_code=201)
def create_record(
    payload: PayrollRecordIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    record, created = _create_record_from_payload(db, payload, current=current)
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, duplicate=not created, employees=employees, departments=departments)


@router.post("/records/bulk", response_model=PayrollBulkOut)
def create_records_bulk(
    payload: PayrollRecordBulkIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    records: list[PayrollRecord] = []
    created_count = 0
    duplicate_count = 0
    created_ids: list[int] = []
    duplicates: set[int] = set()
    for row in payload.records:
        record, created = _create_record_from_payload(
            db,
            row,
            current=current,
            period_id_override=payload.payroll_period_id,
            audit_individual=True,
        )
        records.append(record)
        if created:
            created_count += 1
            created_ids.append(int(record.id))
        else:
            duplicate_count += 1
            duplicates.add(int(record.id))
    log_action(
        db,
        current,
        "bulk_create",
        "PayrollRecord",
        created_ids[0] if created_ids else None,
        new_value={"created_count": created_count, "duplicate_count": duplicate_count, "record_ids": created_ids},
    )
    db.commit()
    for record in records:
        db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(r.employee_id) for r in records})
    return {
        "records": [
            _serialize_record(record, duplicate=int(record.id) in duplicates, employees=employees, departments=departments)
            for record in records
        ],
        "created_count": created_count,
        "duplicate_count": duplicate_count,
    }


@router.post("/records/{record_id}/void", response_model=PayrollRecordOut)
def void_record(
    record_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    record = db.query(PayrollRecord).filter(
        PayrollRecord.id == record_id,
        PayrollRecord.factory_code == factory_code,
    ).with_for_update().first()
    if not record:
        raise HTTPException(404, "Payroll record not found")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll records can only be voided by an admin")
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == record.payroll_period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first() if record.payroll_period_id else None
    if period and period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")
    old_status = record.status
    record.status = "voided"
    log_action(db, current, "void", "PayrollRecord", record.id, old_value={"status": old_status}, new_value={"status": record.status})
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, employees=employees, departments=departments)


@router.post("/records/{record_id}/reverse-as-adjustment", response_model=PayrollAdjustmentOut, status_code=201)
def reverse_record_as_adjustment(
    record_id: int,
    payload: PayrollRecordReversalIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    record = db.query(PayrollRecord).filter(
        PayrollRecord.id == record_id,
        PayrollRecord.factory_code == factory_code,
    ).with_for_update().first()
    if not record:
        raise HTTPException(404, "Payroll record not found")
    if record.status == "voided":
        raise HTTPException(409, "Voided payroll records cannot be reversed")

    source_period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == record.payroll_period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first() if record.payroll_period_id else None
    source_finalized = record.status in {"approved", "paid"} or bool(
        source_period and source_period.status in {"locked", "approved", "paid"}
    )
    if not source_finalized:
        raise HTTPException(409, "Use Void while the source payroll period is still editable")

    target_period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.id == payload.target_period_id,
            PayrollPeriod.factory_code == factory_code,
        )
        .with_for_update()
        .first()
    )
    if not target_period:
        raise HTTPException(404, "Target payroll period not found")
    _assert_period_accepts_adjustments(target_period)
    if target_period.id == record.payroll_period_id:
        raise HTTPException(409, "A reversal must be posted to a different editable payroll period")

    existing = (
        db.query(PayrollAdjustment.id)
        .filter(
            PayrollAdjustment.factory_code == factory_code,
            PayrollAdjustment.source_payroll_record_id == record.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "This payroll record already has a reversal adjustment")

    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reversal reason is required")
    adjustment = PayrollAdjustment(
        factory_code=factory_code,
        payroll_period_id=target_period.id,
        source_payroll_record_id=record.id,
        employee_id=record.employee_id,
        adjustment_type="deduction",
        amount=record.total_amount,
        currency=record.currency,
        reason=reason,
        created_by=current.id,
        created_at=utcnow(),
    )
    db.add(adjustment)
    db.flush()
    log_action(
        db,
        current,
        "create_reversal_adjustment",
        "PayrollAdjustment",
        adjustment.id,
        new_value={
            "source_payroll_record_id": record.id,
            "source_payroll_period_id": record.payroll_period_id,
            "target_payroll_period_id": target_period.id,
            "employee_id": record.employee_id,
            "amount": adjustment.amount,
            "currency": adjustment.currency,
            "reason": adjustment.reason,
        },
    )
    db.commit()
    db.refresh(adjustment)
    return adjustment


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
):
    factory_code = selected_factory_code(current)
    base_qry = _filtered_record_query(
        db,
        factory_code=factory_code,
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    ).filter(PayrollRecord.status != "voided")

    rows = base_qry.all()
    adjustments = _filtered_adjustment_query(
        db,
        factory_code=factory_code,
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    ).all()
    employees, departments = _load_employee_maps(db, {int(r.employee_id) for r in rows} | {int(a.employee_id) for a in adjustments})
    currencies = {str(r.currency or "UZS") for r in rows} | {str(a.currency or "UZS") for a in adjustments}
    summary_currency = next(iter(currencies)) if len(currencies) == 1 else ("MIXED" if currencies else "UZS")

    total_quantity = sum((r.quantity or Decimal("0")) for r in rows) if rows else Decimal("0")
    piecework_amount = sum((r.total_amount or Decimal("0")) for r in rows) if rows else Decimal("0")
    bonus_amount = sum((a.amount or Decimal("0")) for a in adjustments if a.adjustment_type == "bonus") if adjustments else Decimal("0")
    deduction_amount = sum((a.amount or Decimal("0")) for a in adjustments if a.adjustment_type == "deduction") if adjustments else Decimal("0")
    adjustment_amount = bonus_amount - deduction_amount
    total_amount = piecework_amount + adjustment_amount

    employee_groups: dict[tuple[int, str], dict[str, Any]] = {}
    operation_groups: dict[tuple[int, str, str | None, str | None, str | None], dict[str, Any]] = {}

    def employee_group(employee_id_value: int, currency_value: str) -> dict[str, Any]:
        employee = employees.get(int(employee_id_value))
        department = departments.get(int(employee.department_id)) if employee and employee.department_id else None
        return employee_groups.setdefault(
            (int(employee_id_value), currency_value),
            {
                "employee_id": int(employee_id_value),
                "employee_name": employee.full_name if employee else f"Employee {employee_id_value}",
                "department_id": employee.department_id if employee else None,
                "department_name": department.name if department else None,
                "currency": currency_value,
                "records_count": 0,
                "adjustment_count": 0,
                "quantity": Decimal("0"),
                "piecework_amount": Decimal("0"),
                "adjustment_amount": Decimal("0"),
                "bonus_amount": Decimal("0"),
                "deduction_amount": Decimal("0"),
                "total_amount": Decimal("0"),
                "operations": [],
            },
        )

    for record in rows:
        current = employee_group(int(record.employee_id), str(record.currency or "UZS"))
        current["records_count"] += 1
        current["quantity"] += record.quantity or Decimal("0")
        current["piecework_amount"] += record.total_amount or Decimal("0")
        current["total_amount"] += record.total_amount or Decimal("0")

        if group_by_operation:
            operation_key = (
                int(record.employee_id),
                str(record.currency or "UZS"),
                record.operation_section,
                record.operation_code,
                record.operation_name,
            )
            op = operation_groups.setdefault(
                operation_key,
                {
                    "employee_id": int(record.employee_id),
                    "operation_section": record.operation_section,
                    "operation_code": record.operation_code,
                    "operation_name": record.operation_name,
                    "currency": str(record.currency or "UZS"),
                    "records_count": 0,
                    "quantity": Decimal("0"),
                    "total_amount": Decimal("0"),
                },
            )
            op["records_count"] += 1
            op["quantity"] += record.quantity or Decimal("0")
            op["total_amount"] += record.total_amount or Decimal("0")

    for adjustment in adjustments:
        current = employee_group(int(adjustment.employee_id), str(adjustment.currency or "UZS"))
        signed_amount = _adjustment_signed_amount(adjustment)
        current["adjustment_count"] += 1
        current["adjustment_amount"] += signed_amount
        current["total_amount"] += signed_amount
        if adjustment.adjustment_type == "deduction":
            current["deduction_amount"] += adjustment.amount or Decimal("0")
        else:
            current["bonus_amount"] += adjustment.amount or Decimal("0")

    if group_by_operation:
        for key, op in operation_groups.items():
            employee_key = (key[0], key[1])
            employee_groups[employee_key]["operations"].append(PayrollSummaryOperationOut(**op))

    employees_out = [PayrollSummaryEmployeeOut(**row) for row in employee_groups.values()]
    employees_out.sort(key=lambda row: (str(row.employee_name).lower(), row.employee_id))
    return PayrollSummaryOut(
        records_count=len(rows),
        adjustment_count=len(adjustments),
        quantity=total_quantity,
        piecework_amount=piecework_amount,
        adjustment_amount=adjustment_amount,
        bonus_amount=bonus_amount,
        deduction_amount=deduction_amount,
        total_amount=total_amount,
        currency=summary_currency,
        employees=employees_out,
    )


@router.get("/adjustments", response_model=list[PayrollAdjustmentOut])
def list_adjustments(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = _filtered_adjustment_query(
        db,
        factory_code=selected_factory_code(current),
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    return qry.order_by(PayrollAdjustment.id.desc()).all()


@router.post("/adjustments", response_model=PayrollAdjustmentOut, status_code=201)
def create_adjustment(
    payload: PayrollAdjustmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == payload.payroll_period_id,
        PayrollPeriod.factory_code == factory_code,
    ).first() if payload.payroll_period_id else None
    if payload.payroll_period_id and not period:
        raise HTTPException(404, "Payroll period not found")
    _assert_period_accepts_adjustments(period)
    if not db.query(Employee.id).filter(
        Employee.id == payload.employee_id,
        Employee.factory_code == factory_code,
    ).first():
        raise HTTPException(404, "Employee not found")
    amount, adjustment_type = _normalize_adjustment_amount(payload)
    adjustment = PayrollAdjustment(
        factory_code=factory_code,
        payroll_period_id=payload.payroll_period_id,
        employee_id=payload.employee_id,
        adjustment_type=adjustment_type,
        amount=amount,
        currency=(payload.currency or "UZS").upper()[:8],
        reason=payload.reason,
        created_by=current.id,
        created_at=utcnow(),
    )
    db.add(adjustment)
    db.flush()
    log_action(
        db,
        current,
        "create",
        "PayrollAdjustment",
        adjustment.id,
        new_value={
            "employee_id": adjustment.employee_id,
            "adjustment_type": adjustment.adjustment_type,
            "amount": adjustment.amount,
            "signed_amount": _adjustment_signed_amount(adjustment),
            "reason": adjustment.reason,
        },
    )
    db.commit()
    db.refresh(adjustment)
    return adjustment

