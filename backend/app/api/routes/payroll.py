from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_

from app.core.deps import DbSession, require_permissions, is_admin, user_permissions
from app.core.dt import as_utc, utcnow
from app.models import (
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
    PayrollQrLabelOut,
    PayrollQrLabelsIssueIn,
    PayrollQrLabelsIssueOut,
    PayrollRecordBulkIn,
    PayrollRecordIn,
    PayrollRecordOut,
    PayrollSummaryEmployeeOut,
    PayrollSummaryOperationOut,
    PayrollSummaryOut,
)
from app.services.audit import log_action

router = APIRouter(prefix="/payroll", tags=["payroll"])

PERIOD_STATUSES = {"draft", "open", "locked", "approved", "paid", "cancelled"}
RECORD_STATUSES = {"recorded", "voided", "approved", "paid"}
MUTATION_LOCKED_PERIOD_STATUSES = {"locked", "approved", "paid", "cancelled"}
ADJUSTMENT_TYPES = {"bonus", "deduction"}
PAYROLL_WORK_UNITS = {"piece", "work_unit"}
PAYROLL_QR_TOKEN_LENGTH = 9
# QR token type discriminators, not credentials.
PAYROLL_EMPLOYEE_TOKEN_PREFIX = "1"  # nosec B105
PAYROLL_WORK_TOKEN_PREFIX = "2"  # nosec B105
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


def _period_no_for(db: DbSession, start_date: datetime) -> str:
    base = f"PAY-{start_date.year}-{start_date.month:02d}"
    if not db.query(PayrollPeriod.id).filter(PayrollPeriod.period_no == base).first():
        return base
    year_prefix = f"PAY-{start_date.year}-"
    count = db.query(PayrollPeriod.id).filter(PayrollPeriod.period_no.like(f"{year_prefix}%")).count() + 1
    while True:
        candidate = f"{year_prefix}{count:06d}"
        if not db.query(PayrollPeriod.id).filter(PayrollPeriod.period_no == candidate).first():
            return candidate
        count += 1


def _validate_period_dates(start_date: datetime, end_date: datetime) -> None:
    if as_utc(end_date) < as_utc(start_date):
        raise HTTPException(400, "Payroll period end_date must be after start_date")


def _can_period_override(user: User) -> bool:
    perms = user_permissions(user)
    return is_admin(user) or "management.approve" in perms or "payroll.approve" in perms


def _attach_period(db: DbSession, period_id: int | None, scanned_at: datetime) -> PayrollPeriod | None:
    if period_id:
        period = db.get(PayrollPeriod, period_id)
        if not period:
            raise HTTPException(404, "Payroll period not found")
        return period

    period = (
        db.query(PayrollPeriod)
        .filter(
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
        .filter(PayrollPeriod.status == "open")
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


def _validate_and_enrich_record(db: DbSession, data: dict[str, Any]) -> dict[str, Any]:
    employee_id = data.get("employee_id")
    if not employee_id:
        raise HTTPException(400, "employee_id is required")
    employee = db.get(Employee, int(employee_id))
    if not employee:
        raise HTTPException(404, "Employee not found")
    if not data.get("employee_user_id") and employee.user_id:
        data["employee_user_id"] = employee.user_id
    if data.get("employee_user_id") and not db.get(User, int(data["employee_user_id"])):
        raise HTTPException(404, "Employee user not found")

    wo = db.get(WorkOrder, int(data["work_order_id"])) if data.get("work_order_id") else None
    if data.get("work_order_id") and not wo:
        raise HTTPException(404, "Work order not found")
    if wo:
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
    label = db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == label_uid).first()
    if not label:
        label = PayrollQrLabel(label_uid=label_uid, issued_at=record.scanned_at, issued_by=record.scanned_by)
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
    data = _normalize_record_payload(payload)
    payload_period_id = payload.payroll_period_id or _to_int(_extra(payload, "payrollPeriodId"))
    if period_id_override is not None and data.get("payroll_period_id") is None:
        data["payroll_period_id"] = period_id_override
    else:
        data["payroll_period_id"] = payload_period_id

    if data.get("scan_uid"):
        existing = db.query(PayrollRecord).filter(PayrollRecord.scan_uid == data["scan_uid"]).first()
        if existing:
            if data.get("employee_id") and int(existing.employee_id) != int(data["employee_id"]):
                raise HTTPException(
                    409,
                    "This payroll work QR was already recorded for another employee; generate a separate payroll QR for another payable worker/unit",
                )
            return existing, False

    data = _validate_and_enrich_record(db, data)
    existing = db.query(PayrollRecord).filter(PayrollRecord.dedupe_key == data["dedupe_key"]).first()
    if existing:
        return existing, False

    period = _attach_period(db, data.get("payroll_period_id"), data["scanned_at"])
    _assert_period_accepts_records(period, current)
    data["payroll_period_id"] = period.id if period else None

    record = PayrollRecord(
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
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = db.query(PayrollRecord)
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
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = db.query(PayrollAdjustment)
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
    _: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.approve", "payroll.pay", "*")),
    status: str | None = None,
):
    qry = db.query(PayrollPeriod)
    if status:
        qry = qry.filter(PayrollPeriod.status == status)
    return qry.order_by(PayrollPeriod.start_date.desc(), PayrollPeriod.id.desc()).all()


@router.post("/periods", response_model=PayrollPeriodOut, status_code=201)
def create_period(
    payload: PayrollPeriodIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    if payload.status not in PERIOD_STATUSES:
        raise HTTPException(400, "Invalid payroll period status")
    _validate_period_dates(payload.start_date, payload.end_date)
    period_no = payload.period_no.strip() if payload.period_no else _period_no_for(db, payload.start_date)
    if db.query(PayrollPeriod.id).filter(PayrollPeriod.period_no == period_no).first():
        raise HTTPException(400, "Payroll period number already exists")
    period = PayrollPeriod(
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
    period = db.get(PayrollPeriod, period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in PERIOD_STATUSES:
        raise HTTPException(400, "Invalid payroll period status")
    start_date = changes.get("start_date", period.start_date)
    end_date = changes.get("end_date", period.end_date)
    _validate_period_dates(start_date, end_date)
    if changes.get("period_no"):
        exists = db.query(PayrollPeriod.id).filter(
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
    period = db.get(PayrollPeriod, period_id)
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
    period = db.get(PayrollPeriod, period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status in {"paid", "cancelled"}:
        raise HTTPException(409, f"Cannot approve a {period.status} payroll period")
    old_status = period.status
    period.status = "approved"
    period.approved_by = current.id
    period.approved_at = utcnow()
    db.query(PayrollRecord).filter(
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
    period = db.get(PayrollPeriod, period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "approved":
        raise HTTPException(409, "Only approved payroll periods can be marked paid")
    period.status = "paid"
    db.query(PayrollRecord).filter(
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
    _: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
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
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    if status:
        qry = qry.filter(PayrollRecord.status == status)
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


@router.post("/qr-labels/issue", response_model=PayrollQrLabelsIssueOut)
def issue_qr_labels(
    payload: PayrollQrLabelsIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    if not payload.labels:
        raise HTTPException(400, "At least one payroll QR label is required")
    issued_at = utcnow()
    issued_ids: list[int] = []
    issued_labels: list[dict[str, str]] = []
    for row in payload.labels:
        label_uid = row.label_uid.strip()
        if not label_uid or len(label_uid) > 128:
            raise HTTPException(400, "Invalid payroll QR label identifier")
        label = db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == label_uid).first()
        if not label:
            label = PayrollQrLabel(label_uid=label_uid)
            db.add(label)
        active_record = db.query(PayrollRecord).filter(PayrollRecord.scan_uid == label_uid).first()
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
        if active_record:
            label.status = "scanned"
            label.payroll_record_id = active_record.id
            label.last_scanned_at = active_record.scanned_at
        elif label.status != "scanned" or not label.payroll_record_id:
            label.status = "available"
            label.payroll_record_id = None
        db.flush()
        issued_ids.append(int(label.id))
        issued_labels.append({"label_uid": label.label_uid, "qr_token": _work_qr_token(int(label.id))})
    log_action(
        db,
        current,
        "issue",
        "PayrollQrLabel",
        issued_ids[0] if issued_ids else None,
        new_value={"count": len(issued_ids), "label_ids": issued_ids[:100]},
    )
    db.commit()
    return {"issued_count": len(issued_ids), "labels": issued_labels}


@router.get("/qr/resolve/{token}")
def resolve_qr_token(
    token: str,
    db: DbSession,
    _: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    normalized = token.strip()
    if len(normalized) != PAYROLL_QR_TOKEN_LENGTH or not normalized.isdigit():
        raise HTTPException(400, "Payroll QR token must contain exactly 9 digits")

    record_id = int(normalized[1:])
    if normalized.startswith(PAYROLL_EMPLOYEE_TOKEN_PREFIX):
        employee = db.get(Employee, record_id)
        if not employee:
            raise HTTPException(404, "Payroll employee QR was not found")
        department = db.get(Department, employee.department_id) if employee.department_id else None
        department_name = None
        if department:
            department_name = f"{department.code} - {department.name}" if department.code else department.name
        return {
            "type": "employee_payroll",
            "source": "milana_erp_token",
            "badge_id": normalized,
            "employee_id": employee.id,
            "user_id": employee.user_id,
            "employee_name": employee.full_name,
            "department_id": employee.department_id,
            "department_name": department_name,
            "position": employee.position,
            "status": employee.status,
        }

    if normalized.startswith(PAYROLL_WORK_TOKEN_PREFIX):
        label = db.get(PayrollQrLabel, record_id)
        if not label:
            raise HTTPException(404, "Payroll work QR was not found")
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
        }

    raise HTTPException(400, "Unknown payroll QR token type")


@router.get("/qr-labels", response_model=PayrollQrControlOut)
def list_qr_labels(
    db: DbSession,
    _: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
    search: str | None = None,
    status: str | None = None,
    order_no: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    if status and status not in {"available", "scanned"}:
        raise HTTPException(400, "Invalid payroll QR status")
    qry = (
        db.query(PayrollQrLabel)
        .outerjoin(PayrollRecord, PayrollRecord.id == PayrollQrLabel.payroll_record_id)
        .outerjoin(Employee, Employee.id == PayrollRecord.employee_id)
    )
    text_query = (search or "").strip()
    if text_query:
        pattern = f"%{text_query}%"
        search_filters = [
            PayrollQrLabel.label_uid.ilike(pattern),
            PayrollQrLabel.sales_order_no.ilike(pattern),
            PayrollQrLabel.production_no.ilike(pattern),
            PayrollQrLabel.batch_no.ilike(pattern),
            PayrollQrLabel.model_code.ilike(pattern),
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
    available_count = qry.filter(PayrollQrLabel.status == "available").count()
    scanned_count = qry.filter(PayrollQrLabel.status == "scanned").count()
    if status:
        qry = qry.filter(PayrollQrLabel.status == status)
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


@router.post("/qr-labels/{label_id}/return", response_model=PayrollQrLabelOut)
def return_qr_label(
    label_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    label = db.get(PayrollQrLabel, label_id)
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    record = db.get(PayrollRecord, label.payroll_record_id) if label.payroll_record_id else None
    if not record:
        record = db.query(PayrollRecord).filter(PayrollRecord.scan_uid == label.label_uid).first()
    if not record:
        raise HTTPException(409, "This payroll QR is not assigned to an employee")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll QR records can only be returned by an admin")

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
    record = db.get(PayrollRecord, record_id)
    if not record:
        raise HTTPException(404, "Payroll record not found")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll records can only be voided by an admin")
    old_status = record.status
    record.status = "voided"
    log_action(db, current, "void", "PayrollRecord", record.id, old_value={"status": old_status}, new_value={"status": record.status})
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, employees=employees, departments=departments)


@router.get("/summary", response_model=PayrollSummaryOut)
def payroll_summary(
    db: DbSession,
    _: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    group_by_operation: bool = True,
):
    base_qry = _filtered_record_query(
        db,
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    ).filter(PayrollRecord.status != "voided")

    rows = base_qry.all()
    adjustments = _filtered_adjustment_query(
        db,
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
    _: User = Depends(require_permissions("payroll.view", "payroll.manage", "*")),
    period_id: int | None = None,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    qry = _filtered_adjustment_query(
        db,
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
    period = db.get(PayrollPeriod, payload.payroll_period_id) if payload.payroll_period_id else None
    if payload.payroll_period_id and not period:
        raise HTTPException(404, "Payroll period not found")
    _assert_period_accepts_adjustments(period)
    if not db.get(Employee, payload.employee_id):
        raise HTTPException(404, "Employee not found")
    amount, adjustment_type = _normalize_adjustment_amount(payload)
    adjustment = PayrollAdjustment(
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
