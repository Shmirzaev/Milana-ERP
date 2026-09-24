from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import heapq
import json
import re
from types import SimpleNamespace
from typing import Annotated, Any, Callable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy import Date, case, cast, func, or_
from sqlalchemy.orm import load_only, object_session

from app.core.deps import DbSession, require_permissions, is_admin, user_permissions
from app.core.dt import as_utc, utcnow
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.core.order_reference import (
    canonical_order_reference, order_reference_contains, order_reference_variants, resolve_order_id,
)
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
    PayrollAdjustmentPageOut,
    PayrollBulkOut,
    PayrollControlScanIn,
    PayrollControlConfirmIn,
    PayrollNumericWorkScanIn,
    PayrollNumericWorkScanOut,
    PayrollPeriodIn,
    PayrollPeriodOut,
    PayrollPeriodPageOut,
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
    OrderQrStatusOrderOptionPage,
    OrderQrStatusOut,
    PayrollRecordBulkIn,
    PayrollRecordIn,
    PayrollRecordOut,
    PayrollRecordPageOut,
    PayrollRecordReversalIn,
    PayrollSummaryEmployeeOut,
    PayrollSummaryOperationOut,
    PayrollSummaryOut,
    SewingProductionReportOut,
    SewingProductionReportOptions,
)
from app.models.order_reference import BusinessOrderAlias
from app.services.audit import log_action
from app.services.factory_scope import require_factory_access, selected_factory_code
from app.services.paid_operations import filter_operation_rows, paid_operations_from_details
from app.services.payroll_factory_scope import (
    production_order_factory_condition,
    require_production_order_factory,
    require_work_order_factory,
)
from app.services.payroll_reports import ReportLanguage, build_sewing_production_report_xlsx, build_sewing_salary_summary_xlsx, salary_report_days

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
PAYROLL_ADJUSTMENT_MAX_AMOUNT = Decimal("999999999999.99")
PAYROLL_RECORD_COMPONENT_MAX = Decimal("9999999999.9999")
PAYROLL_RECORD_TOTAL_MAX = Decimal("999999999999.99")
PAYROLL_PERIOD_NO_MAX_LENGTH = 64


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
    if not amount.is_finite():
        raise HTTPException(400, "Payroll numeric values must be finite")
    if amount < 0:
        raise HTTPException(400, "Payroll quantity and rates must be non-negative")
    return amount


def _assert_record_numeric_components(quantity: Decimal, rate: Decimal) -> None:
    if quantity > PAYROLL_RECORD_COMPONENT_MAX:
        raise HTTPException(400, "Payroll quantity exceeds the supported maximum of 9999999999.9999")
    if rate > PAYROLL_RECORD_COMPONENT_MAX:
        raise HTTPException(400, "Payroll rate exceeds the supported maximum of 9999999999.9999")


def _assert_record_numeric_storage(quantity: Decimal, rate: Decimal, total: Decimal) -> None:
    _assert_record_numeric_components(quantity, rate)
    if total > PAYROLL_RECORD_TOTAL_MAX:
        raise HTTPException(400, "Payroll total exceeds the supported maximum of 999999999999.99")


def _validated_record_total_amount(quantity: Decimal, rate: Decimal) -> Decimal:
    _assert_record_numeric_components(quantity, rate)
    total = (quantity * rate).quantize(Decimal("0.01"))
    _assert_record_numeric_storage(quantity, rate, total)
    return total


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
    if abs(raw_amount) > PAYROLL_ADJUSTMENT_MAX_AMOUNT:
        raise HTTPException(400, "Adjustment amount exceeds the supported maximum of 999999999999.99")
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


def _canonical_payroll_reference(db, namespace: str, reference: str | None, *, entity_id: int | None = None, production_order_id: int | None = None, lookup=None) -> str | None:
    if db is None or (not reference and entity_id is None):
        return reference
    cache = db.info.setdefault("payroll_order_reference_cache", {})
    key = (namespace, reference, entity_id, production_order_id)
    if key not in cache:
        cache[key] = canonical_order_reference(db, namespace, reference, entity_id=entity_id, production_order_id=production_order_id, lookup=lookup)
    return cache[key]


def _canonical_snapshot_reference(db, namespace: str, reference: str, *, entity_id: int | None = None, production_order_id: int | None = None, lookup=None) -> str:
    canonical = _canonical_payroll_reference(db, namespace, reference, entity_id=entity_id, production_order_id=production_order_id, lookup=lookup)
    if canonical == reference or db is None:
        return reference
    cache = db.info.setdefault("payroll_order_variant_cache", {})
    key = (namespace, canonical, entity_id, production_order_id)
    if key not in cache:
        cache[key] = order_reference_variants(db, namespace, canonical, entity_id=entity_id, production_order_id=production_order_id, lookup=lookup)
    # An ID hint disambiguates real aliases; it must not conceal unrelated text
    # if this snapshot is later compared against the actual printed payload.
    return canonical if reference in cache[key] else reference


def _canonical_payroll_snapshot(db, value: Any, *, production_order_id: int | None = None, sales_order_id: int | None = None, lookup=None) -> Any:
    """Only translate explicit order fields; never rewrite QR identities or money."""
    def resolve(namespace, reference, **identities):
        return _canonical_snapshot_reference(db, namespace, reference, lookup=lookup, **identities)

    return _map_payroll_snapshot_references(value, resolve, production_order_id=production_order_id, sales_order_id=sales_order_id)


def _map_payroll_snapshot_references(value, resolve, *, production_order_id=None, sales_order_id=None):
    """Share the exact payload parsing path between batch preparation and output."""
    if isinstance(value, dict):
        updated = dict(value)
        production_order_id = production_order_id or _to_int(_dget(value, "production_order_id", "pid"))
        sales_order_id = sales_order_id or _to_int(_dget(value, "sales_order_id", "soid"))
        for namespace, keys in (
            ("PO", ("production_no", "productionNo", "po")),
            ("SO", ("sales_order_no", "salesOrderNo", "so")),
        ):
            for key in keys:
                if isinstance(value.get(key), str):
                    updated[key] = resolve(namespace, value[key], entity_id=production_order_id if namespace == "PO" else sales_order_id, production_order_id=production_order_id if namespace == "SO" else None)
        return updated
    if not isinstance(value, str):
        return value
    parts = value.split("*")
    if parts[0].upper() == "MW2":
        production_order_id = production_order_id or (_to_int(parts[1]) if len(parts) > 1 else None)
        sales_order_id = sales_order_id or (_to_int(parts[14]) if len(parts) > 14 else None)
        for index, namespace in ((2, "PO"), (15, "SO")):
            if len(parts) > index and parts[index] != "-":
                parts[index] = resolve(namespace, parts[index], entity_id=production_order_id if namespace == "PO" else sales_order_id, production_order_id=production_order_id if namespace == "SO" else None)
        return "*".join(parts)
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    canonical = _map_payroll_snapshot_references(parsed, resolve, production_order_id=production_order_id, sales_order_id=sales_order_id) if isinstance(parsed, dict) else parsed
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":")) if canonical != parsed else value


def _canonicalize_payroll_input(
    db,
    data: dict[str, Any],
    factory_code: str,
    *,
    lookup=None,
    factory_production_ids: set[int] | None = None,
) -> None:
    for namespace, field in (("PO", "production_no"), ("SO", "sales_order_no")):
        data[field] = _canonical_payroll_reference(
            db,
            namespace,
            data.get(field),
            entity_id=data.get("production_order_id") if namespace == "PO" else data.get("sales_order_id"),
            production_order_id=data.get("production_order_id") if namespace == "SO" else None,
            lookup=lookup,
        )
    # A reference-only legacy QR must undergo the same factory check as an ID QR.
    if not data.get("production_order_id") and data.get("production_no"):
        referenced_id = resolve_order_id(db, "PO", data["production_no"], lookup=lookup)
        if referenced_id is not None:
            if factory_production_ids is None:
                require_production_order_factory(db, referenced_id, factory_code)
            elif referenced_id not in factory_production_ids:
                raise HTTPException(404, "Production order was not found in this factory")
    data["raw_work_json"] = _canonical_payroll_snapshot(
        db,
        data.get("raw_work_json"),
        production_order_id=data.get("production_order_id"),
        sales_order_id=data.get("sales_order_id"),
        lookup=lookup,
    )


def _legacy_payroll_dedupe_keys(db, data: dict[str, Any]) -> set[str]:
    # Existing hashes are immutable. Recreate candidates from this retry's exact
    # numeric/time values, varying only the mapped order names (not DB decimals).
    production_refs = order_reference_variants(db, "PO", data.get("production_no"), entity_id=data.get("production_order_id")) | {data.get("production_no")}
    sales_refs = order_reference_variants(db, "SO", data.get("sales_order_no"), entity_id=data.get("sales_order_id"), production_order_id=data.get("production_order_id")) | {data.get("sales_order_no")}
    return {
        _dedupe_key({**data, "production_no": production_no, "sales_order_no": sales_no})
        for production_no in production_refs for sales_no in sales_refs
    }


def _payroll_order_reference_variants(db, reference: str) -> set[str]:
    # Historical factory SO display aliases now identify actual PO references.
    # Either payroll field may hold that old displayed value; don't infer type
    # merely from which denormalized snapshot column contains it.
    return order_reference_variants(db, "SO", reference) | order_reference_variants(db, "PO", reference) | {reference}


def _payroll_order_reference_match(db, column, namespace: str, pattern: str):
    variants = _payroll_order_reference_variants(db, pattern.strip("%"))
    return or_(order_reference_contains(column, pattern), column.in_(variants))


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
        "total_amount": None,
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


def _can_set_payable_values(user: User) -> bool:
    return is_admin(user) or "payroll.manage" in user_permissions(user)


def _find_period(
    db: DbSession,
    period_id: int | None,
    scanned_at: datetime,
    factory_code: str,
    *,
    for_update: bool,
) -> PayrollPeriod | None:
    def first(query):
        if for_update:
            query = query.populate_existing().with_for_update()
        return query.first()

    if period_id:
        return first(db.query(PayrollPeriod).filter(
            PayrollPeriod.id == period_id, PayrollPeriod.factory_code == factory_code,
        ))

    period = first(
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.factory_code == factory_code,
            PayrollPeriod.status == "open",
            PayrollPeriod.start_date <= scanned_at,
            PayrollPeriod.end_date >= scanned_at,
        )
        .order_by(PayrollPeriod.id.desc())
    )
    return period


def _attach_period(
    db: DbSession,
    period_id: int | None,
    scanned_at: datetime,
    factory_code: str,
) -> PayrollPeriod | None:
    candidate = _find_period(db, period_id, scanned_at, factory_code, for_update=bool(period_id))
    period = candidate
    if candidate is not None and period_id is None:
        # Pin automatic attachment to the candidate seen at request start. If it
        # finalizes while this request waits, the refreshed status rejects the
        # write instead of silently moving it to another period.
        period = _find_period(db, int(candidate.id), scanned_at, factory_code, for_update=True)
    if period_id and not period:
        raise HTTPException(404, "Payroll period not found")
    return period


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


def _validate_and_enrich_record(
    db: DbSession,
    data: dict[str, Any],
    factory_code: str,
    *,
    allow_manual_payable_values: bool,
    locked_labels: dict[str, PayrollQrLabel] | None = None,
    issued_label_validator: Callable[[PayrollQrLabel], None] | None = None,
    validation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = validation_context or {}
    _canonicalize_payroll_input(
        db,
        data,
        factory_code,
        lookup=context.get("order_lookup"),
        factory_production_ids=context.get("factory_production_ids"),
    )
    employee_id = data.get("employee_id")
    if not employee_id:
        raise HTTPException(400, "employee_id is required")
    employee = (
        context["employees"].get(int(employee_id))
        if validation_context is not None else
        db.query(Employee).filter(
            Employee.id == int(employee_id),
            Employee.factory_code == factory_code,
        ).first()
    )
    if not employee:
        raise HTTPException(404, "Employee not found")
    if not data.get("employee_user_id") and employee.user_id:
        data["employee_user_id"] = employee.user_id
    if data.get("employee_user_id"):
        employee_user = (
            context["users"].get(int(data["employee_user_id"]))
            if validation_context is not None else
            db.query(User).filter(
                User.id == int(data["employee_user_id"]),
                User.factory_code == factory_code,
            ).first()
        )
        if not employee_user:
            raise HTTPException(404, "Employee user not found")

    wo = (
        context["work_orders"].get(int(data["work_order_id"]))
        if validation_context is not None and data.get("work_order_id") else
        db.get(WorkOrder, int(data["work_order_id"])) if data.get("work_order_id") else None
    )
    if data.get("work_order_id") and not wo:
        raise HTTPException(404, "Work order not found")
    if wo:
        if validation_context is not None:
            if int(wo.production_order_id) not in context["factory_production_ids"]:
                raise HTTPException(404, "Work order was not found in this factory")
        else:
            require_work_order_factory(db, wo, factory_code)
        if data.get("production_order_id") and int(data["production_order_id"]) != int(wo.production_order_id):
            raise HTTPException(400, "work_order_id does not belong to production_order_id")
        if wo.production_batch_id and data.get("production_batch_id") and int(data["production_batch_id"]) != int(wo.production_batch_id):
            raise HTTPException(400, "production_batch_id does not belong to work_order_id")
        data["production_order_id"] = wo.production_order_id
        data["production_batch_id"] = data.get("production_batch_id") or wo.production_batch_id
        data["operation_section"] = data.get("operation_section") or wo.operation

    po = (
        context["production_orders"].get(int(data["production_order_id"]))
        if validation_context is not None and data.get("production_order_id") else
        db.get(ProductionOrder, int(data["production_order_id"])) if data.get("production_order_id") else None
    )
    if data.get("production_order_id") and not po:
        raise HTTPException(404, "Production order not found")
    if po:
        if validation_context is not None:
            if int(po.id) not in context["factory_production_ids"]:
                raise HTTPException(404, "Production order was not found in this factory")
        else:
            require_production_order_factory(db, int(po.id), factory_code)
        data["production_no"] = po.production_no
        data["sales_order_id"] = data.get("sales_order_id") or po.sales_order_id
        data["model_id"] = data.get("model_id") or po.model_id

    so = (
        context["sales_orders"].get(int(data["sales_order_id"]))
        if validation_context is not None and data.get("sales_order_id") else
        db.get(SalesOrder, int(data["sales_order_id"])) if data.get("sales_order_id") else None
    )
    if data.get("sales_order_id") and not so:
        raise HTTPException(404, "Sales order not found")
    if so:
        data["sales_order_no"] = so.order_no

    batch = (
        context["production_batches"].get(int(data["production_batch_id"]))
        if validation_context is not None and data.get("production_batch_id") else
        db.get(ProductionBatch, int(data["production_batch_id"])) if data.get("production_batch_id") else None
    )
    if data.get("production_batch_id") and not batch:
        raise HTTPException(404, "Production batch not found")
    if batch:
        if data.get("production_order_id") and int(batch.production_order_id) != int(data["production_order_id"]):
            raise HTTPException(400, "production_batch_id does not belong to production_order_id")
        data["production_order_id"] = data.get("production_order_id") or batch.production_order_id
        data["batch_no"] = data.get("batch_no") or batch.batch_no

    model = (
        context["models"].get(int(data["model_id"]))
        if validation_context is not None and data.get("model_id") else
        db.get(Model, int(data["model_id"])) if data.get("model_id") else None
    )
    if data.get("model_id") and not model:
        raise HTTPException(404, "Model not found")
    if model:
        data["model_code"] = data.get("model_code") or model.code

    issued_label = None
    if data.get("scan_uid"):
        if locked_labels is not None:
            issued_label = locked_labels.get(data["scan_uid"])
        else:
            issued_label = (
                db.query(PayrollQrLabel)
                .filter(
                    PayrollQrLabel.label_uid == data["scan_uid"],
                    PayrollQrLabel.factory_code == factory_code,
                )
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )
    if not issued_label and not allow_manual_payable_values:
        raise HTTPException(403, "Payroll scan requires an issued payroll QR with server-approved pay values")
    if issued_label:
        if issued_label.status == "superseded":
            raise HTTPException(409, "This payroll QR was replaced by split labels and can no longer be scanned")
        if issued_label.status != "available":
            raise HTTPException(409, "This payroll QR is not available for scanning")
        if issued_label_validator:
            issued_label_validator(issued_label)
        data.update({
            "production_order_id": issued_label.production_order_id,
            "sales_order_id": issued_label.sales_order_id,
            "work_order_id": issued_label.work_order_id,
            "production_batch_id": issued_label.production_batch_id,
            "model_id": issued_label.model_id,
            "production_no": _canonical_payroll_reference(
                db, "PO", issued_label.production_no,
                entity_id=issued_label.production_order_id, lookup=context.get("order_lookup"),
            ),
            "sales_order_no": _canonical_payroll_reference(
                db, "SO", issued_label.sales_order_no,
                entity_id=issued_label.sales_order_id,
                production_order_id=issued_label.production_order_id,
                lookup=context.get("order_lookup"),
            ),
            "batch_no": _normalize_production_batch_no(issued_label.batch_no),
            "model_code": issued_label.model_code,
            "operation_section": issued_label.operation_section,
            "operation_code": issued_label.operation_code,
            "operation_name": issued_label.operation_name,
            "quantity": _to_decimal(issued_label.quantity),
            "rate_per_piece": _to_decimal(issued_label.rate_per_piece),
            "currency": issued_label.currency,
        })
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

    data["total_amount"] = _validated_record_total_amount(
        data["quantity"], data["rate_per_piece"],
    )

    data["factory_code"] = factory_code
    data["operation_name"] = data.get("operation_name") or data.get("operation_code") or data.get("operation_section")
    data["dedupe_key"] = _dedupe_key(data)
    return data


def _load_employee_maps(db: DbSession, employee_ids: set[int]) -> tuple[dict[int, Employee], dict[int, Department]]:
    employees = {
        int(e.id): e
        for e in (
            db.query(Employee)
            .options(load_only(Employee.id, Employee.full_name, Employee.department_id))
            .filter(Employee.id.in_(employee_ids))
            .all()
            if employee_ids
            else []
        )
    }
    department_ids = {int(e.department_id) for e in employees.values() if e.department_id}
    departments = {
        int(d.id): d
        for d in (
            db.query(Department)
            .options(load_only(Department.id, Department.name))
            .filter(Department.id.in_(department_ids))
            .all()
            if department_ids
            else []
        )
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
        "production_no": _canonical_payroll_reference(object_session(record), "PO", record.production_no, entity_id=record.production_order_id),
        "sales_order_no": _canonical_payroll_reference(object_session(record), "SO", record.sales_order_no, entity_id=record.sales_order_id, production_order_id=record.production_order_id),
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
        "raw_work_json": _canonical_payroll_snapshot(object_session(record), record.raw_work_json, production_order_id=record.production_order_id, sales_order_id=record.sales_order_id),
        "status": record.status,
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "duplicate": duplicate,
    }


def _mark_qr_label_scanned(
    db: DbSession,
    record: PayrollRecord,
    data: dict[str, Any],
    *,
    locked_labels: dict[str, PayrollQrLabel] | None = None,
) -> None:
    label_uid = _to_text(record.scan_uid)
    if not label_uid:
        return
    raw_work = data.get("raw_work_json") if isinstance(data.get("raw_work_json"), dict) else {}
    label = (
        locked_labels.get(label_uid)
        if locked_labels is not None else
        db.query(PayrollQrLabel).filter(
            PayrollQrLabel.label_uid == label_uid,
            PayrollQrLabel.factory_code == record.factory_code,
        ).first()
    )
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


_PERIOD_NOT_PRELOCKED = object()


def _prepare_record_data(payload: PayrollRecordIn, period_id_override: int | None) -> dict[str, Any]:
    data = _normalize_record_payload(payload)
    payload_period_id = payload.payroll_period_id or _to_int(_extra(payload, "payrollPeriodId"))
    if period_id_override is not None and data.get("payroll_period_id") is None:
        data["payroll_period_id"] = period_id_override
    else:
        data["payroll_period_id"] = payload_period_id
    return data


def _create_record_from_payload(
    db: DbSession,
    payload: PayrollRecordIn,
    *,
    current: User,
    period_id_override: int | None = None,
    audit_individual: bool = True,
    control_confirmed: bool = False,
    prepared_data: dict[str, Any] | None = None,
    prelocked_period: PayrollPeriod | None | object = _PERIOD_NOT_PRELOCKED,
    locked_labels: dict[str, PayrollQrLabel] | None = None,
    issued_label_validator: Callable[[PayrollQrLabel], None] | None = None,
    validation_context: dict[str, Any] | None = None,
    data_is_validated: bool = False,
    known_scan_records: dict[str, PayrollRecord] | None = None,
    known_dedupe_records: dict[str, PayrollRecord] | None = None,
) -> tuple[PayrollRecord, bool]:
    factory_code = selected_factory_code(current)
    data = dict(prepared_data) if prepared_data is not None else _prepare_record_data(payload, period_id_override)

    if data.get("scan_uid"):
        existing = (
            known_scan_records.get(data["scan_uid"])
            if known_scan_records is not None else
            db.query(PayrollRecord).filter(
                PayrollRecord.factory_code == factory_code,
                PayrollRecord.scan_uid == data["scan_uid"],
            ).first()
        )
        if existing:
            if data.get("employee_id") and int(existing.employee_id) != int(data["employee_id"]):
                raise HTTPException(
                    409,
                    "This payroll work QR was already recorded for another employee; generate a separate payroll QR for another payable worker/unit",
                )
            return existing, False

    if prelocked_period is _PERIOD_NOT_PRELOCKED:
        period = _attach_period(db, data.get("payroll_period_id"), data["scanned_at"], factory_code)
    else:
        period = prelocked_period
        if data.get("payroll_period_id") and period is None:
            raise HTTPException(404, "Payroll period not found")

    if not data_is_validated:
        data = _validate_and_enrich_record(
            db,
            data,
            factory_code,
            allow_manual_payable_values=_can_set_payable_values(current),
            locked_labels=locked_labels,
            issued_label_validator=issued_label_validator,
            validation_context=validation_context,
        )
    if _is_control_operation(data) and not control_confirmed:
        raise HTTPException(409, "Control operation requires review and confirmation before payroll is recorded")
    existing = (
        known_dedupe_records.get(data["dedupe_key"])
        if known_dedupe_records is not None else
        db.query(PayrollRecord).filter(
            PayrollRecord.dedupe_key == data["dedupe_key"],
            PayrollRecord.factory_code == factory_code,
        ).first()
    )
    if existing:
        return existing, False

    if not data.get("scan_uid"):
        existing = db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid.is_(None),
            PayrollRecord.dedupe_key.in_(_legacy_payroll_dedupe_keys(db, data)),
        ).first()
        if existing:
            return existing, False

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
    _mark_qr_label_scanned(db, record, data, locked_labels=locked_labels)
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


@router.get("/periods", response_model=list[PayrollPeriodOut] | PayrollPeriodPageOut)
def list_periods(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.approve", "payroll.pay", "*")),
    status: str | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    qry = db.query(PayrollPeriod).filter(PayrollPeriod.factory_code == selected_factory_code(current))
    if status:
        qry = qry.filter(PayrollPeriod.status == status)
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = qry.order_by(None).count()
    ordered_qry = qry.order_by(PayrollPeriod.start_date.desc(), PayrollPeriod.id.desc())
    if total is None:
        return ordered_qry.all()
    rows = ordered_qry.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


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
    if len(payload.name) > 128:
        raise HTTPException(422, "Payroll period name exceeds the 128-character storage limit")
    if len(period_no) > PAYROLL_PERIOD_NO_MAX_LENGTH:
        raise HTTPException(422, "Payroll period number exceeds the 64-character storage limit")
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
    ).populate_existing().with_for_update().first()
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
    if "name" in changes and changes["name"] is not None and len(changes["name"]) > 128:
        raise HTTPException(422, "Payroll period name exceeds the 128-character storage limit")
    if (
        "period_no" in changes
        and changes["period_no"] is not None
        and len(changes["period_no"]) > PAYROLL_PERIOD_NO_MAX_LENGTH
    ):
        raise HTTPException(422, "Payroll period number exceeds the 64-character storage limit")
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
    ).populate_existing().with_for_update().first()
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
    ).populate_existing().with_for_update().first()
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
    ).populate_existing().with_for_update().first()
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
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 200
        total = qry.order_by(None).count()
    qry = qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc())
    if total is None:
        qry = qry.limit(max(1, min(limit, 1000)))
    else:
        qry = qry.offset((page - 1) * page_size).limit(page_size)
    rows = qry.all()
    employees, departments = _load_employee_maps(db, {int(r.employee_id) for r in rows})
    payloads = [_serialize_record(r, employees=employees, departments=departments) for r in rows]
    if total is None:
        return payloads
    return {
        "rows": payloads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


def _serialize_qr_label(
    label: PayrollQrLabel,
    *,
    records: dict[int, PayrollRecord],
    employees: dict[int, Employee],
    departments: dict[int, Department],
    order_lookup=None,
) -> dict[str, Any]:
    record = records.get(int(label.payroll_record_id)) if label.payroll_record_id else None
    employee = employees.get(int(record.employee_id)) if record else None
    department = departments.get(int(employee.department_id)) if employee and employee.department_id else None
    return {
        "id": label.id,
        "factory_code": label.factory_code,
        "label_uid": label.label_uid,
        "qr_token": _work_qr_token(int(label.id)),
        "payload": _canonical_payroll_snapshot(object_session(label), label.payload, production_order_id=label.production_order_id, sales_order_id=label.sales_order_id, lookup=order_lookup),
        "production_order_id": label.production_order_id,
        "sales_order_id": label.sales_order_id,
        "work_order_id": label.work_order_id,
        "production_batch_id": label.production_batch_id,
        "model_id": label.model_id,
        "production_no": _canonical_payroll_reference(object_session(label), "PO", label.production_no, entity_id=label.production_order_id, lookup=order_lookup),
        "sales_order_no": _canonical_payroll_reference(object_session(label), "SO", label.sales_order_no, entity_id=label.sales_order_id, production_order_id=label.production_order_id, lookup=order_lookup),
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
    variants = _payroll_order_reference_variants(db, order_no)
    return db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == factory_code,
        PayrollQrLabel.status != "superseded",
        or_(
            PayrollQrLabel.sales_order_no.in_(variants),
            PayrollQrLabel.production_no.in_(variants),
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


def _order_qr_status_option_query(db: DbSession, factory_code: str, search: str | None):
    qry = db.query(
        PayrollQrLabel.sales_order_no.label("sales_order_no"),
        PayrollQrLabel.production_no.label("production_no"),
        PayrollQrLabel.model_code.label("model_code"),
        func.count(PayrollQrLabel.id).label("label_count"),
        func.max(PayrollQrLabel.issued_at).label("latest_at"),
    ).filter(
        PayrollQrLabel.factory_code == factory_code,
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
            _payroll_order_reference_match(db, PayrollQrLabel.sales_order_no, "SO", pattern),
            _payroll_order_reference_match(db, PayrollQrLabel.production_no, "PO", pattern),
        ))
    return qry.group_by(
        PayrollQrLabel.sales_order_no,
        PayrollQrLabel.production_no,
        PayrollQrLabel.model_code,
    ).order_by(func.max(PayrollQrLabel.issued_at).desc())


def _group_order_qr_status_options(rows) -> dict[str, dict[str, Any]]:
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
    return grouped


def _order_qr_status_option_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_no": row["order_no"],
        "sales_order_nos": sorted(row["sales_order_nos"]),
        "production_nos": sorted(row["production_nos"]),
        "model_codes": sorted(row["model_codes"]),
        "label_count": row["label_count"],
    }


@router.get(
    "/reports/order-qr-status/orders",
    response_model=list[OrderQrStatusOrderOption] | OrderQrStatusOrderOptionPage,
)
def order_qr_status_orders(
    db: DbSession,
    current: User = Depends(require_permissions("payroll.view", "payroll.manage", "payroll.pay", "*")),
    search: str | None = None,
    limit: int = 50,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
):
    grouped_query = _order_qr_status_option_query(db, selected_factory_code(current), search)
    safe_limit = max(1, min(limit, 100))
    if page is None and page_size is None:
        grouped = _group_order_qr_status_options(grouped_query.limit(500).all())
        ordered = sorted(
            grouped.values(),
            key=lambda row: row["latest_at"].timestamp() if row["latest_at"] else 0,
            reverse=True,
        )
        return [_order_qr_status_option_payload(row) for row in ordered[:safe_limit]]

    effective_page = page or 1
    effective_page_size = page_size or safe_limit
    limited_rows = grouped_query.limit(500).subquery()
    raw_order_key = case(
        (limited_rows.c.sales_order_no != "", limited_rows.c.sales_order_no),
        else_=limited_rows.c.production_no,
    )
    order_key = func.trim(raw_order_key)
    latest_at = func.max(limited_rows.c.latest_at)
    directory = (
        db.query(order_key.label("order_key"), latest_at.label("latest_at"))
        .filter(order_key != "")
        .group_by(order_key)
    )
    total = int(directory.count())
    key_rows = (
        directory.order_by(latest_at.desc())
        .offset((effective_page - 1) * effective_page_size)
        .limit(effective_page_size)
        .all()
    )
    selected_keys = [str(row.order_key) for row in key_rows]
    detail_rows = []
    if selected_keys:
        detail_rows = db.query(
            limited_rows.c.sales_order_no,
            limited_rows.c.production_no,
            limited_rows.c.model_code,
            limited_rows.c.label_count,
            limited_rows.c.latest_at,
        ).filter(order_key.in_(selected_keys)).all()
    grouped = _group_order_qr_status_options(detail_rows)
    return {
        "rows": [
            _order_qr_status_option_payload(grouped[key])
            for key in selected_keys
            if key in grouped
        ],
        "total": total,
        "page": effective_page,
        "page_size": effective_page_size,
        "has_more": effective_page * effective_page_size < total,
    }


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
    reference_label = all_labels[0]
    reference_namespace = "PO" if exact_order.upper().startswith(("PO-", "USL-")) else "SO"
    canonical_report_order = _canonical_payroll_reference(
        db, reference_namespace, exact_order,
        entity_id=reference_label.production_order_id if reference_namespace == "PO" else reference_label.sales_order_id,
        production_order_id=reference_label.production_order_id if reference_namespace == "SO" else None,
    )

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
        "order_no": canonical_report_order,
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
            if section not in {"sewing", "tikuv"}:
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
        qry = qry.filter(or_(_payroll_order_reference_match(db, PayrollRecord.production_no, "PO", pattern), _payroll_order_reference_match(db, PayrollRecord.sales_order_no, "SO", pattern)))
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


def _sewing_salary_summary(qry) -> list[dict]:
    # Aggregate the complete filtered ledger before any scan pagination.
    day = (cast(func.timezone("Asia/Tashkent", PayrollRecord.scanned_at), Date)
           if qry.session.get_bind().dialect.name == "postgresql"
           else func.date(PayrollRecord.scanned_at, "+5 hours"))
    rows = qry.with_entities(
        PayrollRecord.employee_id,
        Employee.employee_no,
        Employee.full_name,
        PayrollRecord.currency,
        day,
        func.count(PayrollRecord.id),
        func.coalesce(func.sum(PayrollRecord.quantity), 0),
        func.coalesce(func.sum(PayrollRecord.total_amount), 0),
    ).group_by(
        PayrollRecord.employee_id, Employee.employee_no, Employee.full_name, PayrollRecord.currency, day,
    ).order_by(Employee.full_name, PayrollRecord.employee_id, PayrollRecord.currency, day).all()
    employees = {}
    for employee_id, employee_no, name, currency, work_day, count, quantity, amount in rows:
        key = (employee_id, currency)
        item = employees.setdefault(key, {
            "employee_id": employee_id, "employee_no": employee_no, "employee_name": name,
            "currency": currency, "record_count": 0, "quantity": Decimal("0"),
            "total_amount": Decimal("0"), "daily_amounts": {},
        })
        item["record_count"] += count
        item["quantity"] += quantity
        item["total_amount"] += amount
        item["daily_amounts"][str(work_day)] = amount
    return list(employees.values())


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
    salary_summary = _sewing_salary_summary(qry) if report_view == "salary" else []
    rows = [] if report_view == "salary" else (
        qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )

    items = _sewing_production_report_items(rows)
    return {
        "items": items,
        "salary_summary": salary_summary,
        "salary_days": salary_report_days(salary_summary, date_from, date_to) if report_view == "salary" else [],
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
    report_view: Literal["details", "salary"] = "details",
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
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
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
    if report_view == "salary":
        items = _sewing_salary_summary(qry)
        if page is not None:
            total = len(items)
            start = (page - 1) * page_size
            items = items[start:start + page_size]
    else:
        ordered_query = qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc())
        if page is not None:
            total = ordered_query.order_by(None).count()
            ordered_query = ordered_query.offset((page - 1) * page_size).limit(page_size)
        rows = ordered_query.all()
        items = _sewing_production_report_items(rows)
    currencies = {str(item["currency"]) for item in items if item.get("currency")}
    report_currency = next(iter(currencies)) if len(currencies) == 1 else ("MIXED" if currencies else "UZS")
    generated_at = datetime.now(ZoneInfo("Asia/Tashkent"))
    builder = build_sewing_salary_summary_xlsx if report_view == "salary" else build_sewing_production_report_xlsx
    workbook = builder(
        items,
        date_from=date_from,
        date_to=date_to,
        generated_label=generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        lang=lang,
        currency=report_currency,
    )
    report_name = "sewing-salary-summary" if report_view == "salary" else "sewing-production-report"
    filename = f"{report_name}-{generated_at.strftime('%Y-%m-%d')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if total is not None:
        headers.update({
            "X-Total-Count": str(total),
            "X-Page": str(page),
            "X-Page-Size": str(page_size),
            "X-Has-More": "true" if page * page_size < total else "false",
        })
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/qr-labels/issue", response_model=PayrollQrLabelsIssueOut)
def issue_qr_labels(
    payload: PayrollQrLabelsIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    if not payload.labels:
        raise HTTPException(400, "At least one payroll QR label is required")
    issued_at = utcnow()
    factory_code = selected_factory_code(current)
    issued_ids: list[int] = []
    created_ids: list[int] = []
    created_label_uids: set[str] = set()
    existing_count = 0
    issued_labels: list[dict[str, str]] = []

    # Read request-scoped identities once.  Validation below still runs in the
    # original row order, but does not turn a 50-label issue into 100+ SELECTs.
    flow_ids = {int(row.sewing_flow_id) for row in payload.labels if row.sewing_flow_id is not None}
    work_order_ids = {int(row.work_order_id) for row in payload.labels if row.work_order_id is not None}
    production_order_ids = {
        int(row.production_order_id) for row in payload.labels if row.production_order_id is not None
    }
    flow_by_id = (
        {int(flow.id): flow for flow in db.query(SewingFlow).filter(
            SewingFlow.id.in_(flow_ids), SewingFlow.factory_code == factory_code,
        ).all()}
        if flow_ids else {}
    )
    work_order_by_id = (
        {int(work_order.id): work_order for work_order in db.query(WorkOrder).filter(
            WorkOrder.id.in_(work_order_ids),
        ).all()}
        if work_order_ids else {}
    )
    referenced_production_ids = production_order_ids | {
        int(work_order.production_order_id)
        for work_order in work_order_by_id.values()
    }
    normalized_uids = [row.label_uid.strip() for row in payload.labels]
    order_lookup = _issue_order_lookup(db, payload.labels)
    uid_values = {uid for uid in normalized_uids if uid and len(uid) <= 128}
    labels_by_uid = (
        {label.label_uid: label for label in db.query(PayrollQrLabel).filter(
            PayrollQrLabel.factory_code == factory_code,
            PayrollQrLabel.label_uid.in_(uid_values),
        ).all()}
        if uid_values else {}
    )
    inferred_uids: set[str] = set()
    for row in payload.labels:
        label_uid = row.label_uid.strip()
        if (
            row.production_order_id is None
            and row.production_no
            and label_uid not in labels_by_uid
            and label_uid not in inferred_uids
        ):
            inferred_uids.add(label_uid)
            try:
                referenced = resolve_order_id(db, "PO", row.production_no, lookup=order_lookup)
            except HTTPException:
                # Preserve the original row-order error from canonicalization.
                continue
            if referenced is not None:
                referenced_production_ids.add(int(referenced))
    factory_production_ids = (
        {
            int(production_id)
            for (production_id,) in db.query(ProductionOrder.id).filter(
                ProductionOrder.id.in_(referenced_production_ids),
                production_order_factory_condition(factory_code),
            ).all()
        }
        if referenced_production_ids else set()
    )
    new_label_uids: set[str] = set()
    for row in payload.labels:
        if row.sewing_flow_id is not None:
            flow = flow_by_id.get(int(row.sewing_flow_id))
            if not flow:
                raise HTTPException(404, "Sewing line was not found in this factory")
        work_order = work_order_by_id.get(int(row.work_order_id)) if row.work_order_id is not None else None
        if row.work_order_id is not None and not work_order:
            raise HTTPException(404, "Work order not found")
        if work_order:
            if int(work_order.production_order_id) not in factory_production_ids:
                raise HTTPException(404, "Work order was not found in this factory")
            if row.production_order_id is not None and int(work_order.production_order_id) != int(row.production_order_id):
                raise HTTPException(400, "Work order does not belong to the production order")
        if row.production_order_id is not None:
            if int(row.production_order_id) not in factory_production_ids:
                raise HTTPException(404, "Production order was not found in this factory")
        label_uid = row.label_uid.strip()
        if not label_uid or len(label_uid) > 128:
            raise HTTPException(400, "Invalid payroll QR label identifier")
        label = labels_by_uid.get(label_uid)
        is_new = label is None
        if is_new:
            label = PayrollQrLabel(factory_code=factory_code, label_uid=label_uid)
            db.add(label)
            labels_by_uid[label_uid] = label
            new_label_uids.add(label_uid)
            values = row.model_dump(exclude={"label_uid"})
            _canonicalize_payroll_input(
                db,
                values,
                factory_code,
                lookup=order_lookup,
                factory_production_ids=factory_production_ids,
            )
            values.pop("raw_work_json", None)
            values["payload"] = _canonical_payroll_snapshot(
                db,
                row.payload,
                production_order_id=row.production_order_id,
                sales_order_id=row.sales_order_id,
                lookup=order_lookup,
            )
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
            # A shared process code must not make a different payable operation
            # silently appear issued. Rate/quantity corrections retain the UID;
            # a different operation name requires explicit identity review.
            if (
                row.operation_name
                and label.operation_name
                and row.operation_name.strip().casefold() != label.operation_name.strip().casefold()
            ):
                raise HTTPException(409, "Payroll QR identifier already belongs to another paid operation; refresh the issued labels")
            existing_count += 1
        if is_new:
            label.status = "available"
            label.payroll_record_id = None

    # Flush identities, then re-read matching records after all label
    # validation/creation.  This preserves the old same-request duplicate UID
    # behavior and observes a record that appeared while preparation ran.
    db.flush()
    record_uids = set(labels_by_uid).intersection(uid_values)
    records_by_uid = (
        {record.scan_uid: record for record in db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid.in_(record_uids),
        ).all()}
        if record_uids else {}
    )
    for row, label_uid in zip(payload.labels, normalized_uids):
        label = labels_by_uid[label_uid]
        active_record = records_by_uid.get(label_uid)
        is_new = label_uid in new_label_uids
        if active_record:
            label.status = "scanned"
            label.payroll_record_id = active_record.id
            label.last_scanned_at = active_record.scanned_at
        elif is_new:
            label.status = "available"
            label.payroll_record_id = None
        issued_ids.append(int(label.id))
        if is_new and label_uid not in created_label_uids:
            created_label_uids.add(label_uid)
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


def _employee_scan_payload(
    employee: Employee, *, badge_id: str, source: str, db: DbSession,
    departments: dict[int, Department] | None = None,
) -> dict[str, Any]:
    department = (
        departments.get(employee.department_id) if departments is not None
        else db.get(Department, employee.department_id) if employee.department_id else None
    )
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


@router.get("/employees/search")
def search_payroll_employees(
    db: DbSession,
    q: str = Query(min_length=2, max_length=100),
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    terms = q.strip().split()
    if len(q.strip()) < 2:
        return {"items": [], "has_more": False}
    query = db.query(Employee, Department).options(
        load_only(
            Employee.id,
            Employee.employee_no,
            Employee.user_id,
            Employee.full_name,
            Employee.department_id,
            Employee.position,
            Employee.status,
        ),
        load_only(Department.id, Department.code, Department.name),
    ).outerjoin(Department, Employee.department_id == Department.id).filter(
        Employee.factory_code == selected_factory_code(current),
        Employee.status == "active",
    )
    for term in terms:
        # Treat scanner/operator input literally, including SQL wildcard characters.
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(or_(
            Employee.full_name.ilike(pattern, escape="\\"),
            Employee.employee_no.ilike(pattern, escape="\\"),
        ))
    rows = query.order_by(func.lower(Employee.full_name), Employee.employee_no, Employee.id).limit(21).all()
    departments = {department.id: department for _, department in rows if department is not None}
    return {
        "items": [
            _employee_scan_payload(
                employee, badge_id=employee.employee_no or _employee_qr_token(employee.id),
                source="milana_erp_employee_search", db=db, departments=departments,
            )
            for employee, _ in rows[:20]
        ],
        "has_more": len(rows) > 20,
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


def _qr_label_scan_payload(label: PayrollQrLabel) -> dict[str, Any]:
    return {
        "type": "process_payroll",
        "source": "milana_erp_token",
        "label_id": label.label_uid,
        "production_order_id": label.production_order_id,
        "production_no": _canonical_payroll_reference(object_session(label), "PO", label.production_no, entity_id=label.production_order_id),
        "sales_order_id": label.sales_order_id,
        "sales_order_no": _canonical_payroll_reference(object_session(label), "SO", label.sales_order_no, entity_id=label.sales_order_id, production_order_id=label.production_order_id),
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
        "requires_control_confirmation": _is_control_operation(label),
    }


def _is_control_operation(value: PayrollQrLabel | dict[str, Any]) -> bool:
    aliases = {"control", "kontrol", "контроль", "nazorat", "qc"}
    for field in ("operation_section", "operation_name", "operation_code"):
        text = value.get(field) if isinstance(value, dict) else getattr(value, field, None)
        if aliases.intersection(re.findall(r"[^\W\d_]+", str(text or "").casefold())):
            return True
    return False


def _control_review_token(label: PayrollQrLabel, employee_id: int) -> str:
    snapshot = _qr_label_scan_payload(label)
    snapshot.pop("label_status", None)  # Successful confirmation/retry keeps its identity.
    snapshot.update(factory_code=label.factory_code, employee_id=employee_id, return_count=label.return_count)
    return hashlib.sha256(json.dumps(jsonable_encoder(snapshot), sort_keys=True).encode()).hexdigest()


def _control_preview(db: DbSession, label: PayrollQrLabel, employee_id: int) -> dict[str, Any]:
    # Exact context prevents a manual order or another size/factory leaking into review.
    query = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == label.factory_code,
        PayrollQrLabel.status != "superseded",
        PayrollQrLabel.size == label.size,
        PayrollQrLabel.model_id == label.model_id,
    )
    if not label.model_id:
        query = query.filter(PayrollQrLabel.model_code == label.model_code)
    if label.production_order_id:
        query = query.filter(PayrollQrLabel.production_order_id == label.production_order_id)
    else:
        query = query.filter(
            PayrollQrLabel.production_order_id.is_(None),
            PayrollQrLabel.sales_order_no == label.sales_order_no,
            PayrollQrLabel.production_no == label.production_no,
            PayrollQrLabel.batch_no == label.batch_no,
            PayrollQrLabel.cutting_passport_no == label.cutting_passport_no,
        )
        if not any((label.sales_order_no, label.production_no, label.batch_no, label.cutting_passport_no)):
            # An unidentifiable legacy context must not combine unrelated work.
            query = query.filter(PayrollQrLabel.label_uid == label.label_uid)
    labels = query.order_by(PayrollQrLabel.id).all()
    record_ids = {row.payroll_record_id for row in labels if row.payroll_record_id}
    records = {
        row.id: row for row in db.query(PayrollRecord).filter(
            PayrollRecord.id.in_(record_ids), PayrollRecord.factory_code == label.factory_code,
        ).all()
    } if record_ids else {}
    employees, departments = _load_employee_maps(db, {row.employee_id for row in records.values()})
    return {
        "review_token": _control_review_token(label, employee_id),
        "work": _qr_label_scan_payload(label),
        "operations": [
            _serialize_qr_label(row, records=records, employees=employees, departments=departments)
            for row in labels
        ],
    }


def _assert_control_not_voided(db: DbSession, label: PayrollQrLabel) -> None:
    voided = db.query(PayrollRecord.id).filter(
        PayrollRecord.factory_code == label.factory_code,
        PayrollRecord.status == "voided",
        or_(PayrollRecord.id == label.payroll_record_id, PayrollRecord.scan_uid == label.label_uid),
    ).first()
    if voided:
        raise HTTPException(409, "This Control payroll record was cancelled; return the QR before scanning it again")


def _load_control_scan(
    db: DbSession,
    payload: PayrollControlScanIn,
    current: User,
    *,
    for_update: bool = True,
) -> PayrollQrLabel:
    factory_code = selected_factory_code(current)
    query = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.label_uid == payload.label_uid,
        PayrollQrLabel.factory_code == factory_code,
    )
    label = (query.populate_existing().with_for_update() if for_update else query).first()
    if not label:
        raise HTTPException(404, "Issued payroll control QR was not found")
    if label.status == "superseded":
        raise HTTPException(409, "This payroll QR was replaced by split labels and can no longer be scanned")
    if not _is_control_operation(label):
        raise HTTPException(400, "This QR is not a control operation")
    _assert_control_not_voided(db, label)
    if not db.query(Employee.id).filter(
        Employee.id == payload.employee_id, Employee.factory_code == factory_code,
    ).first():
        raise HTTPException(404, "Employee not found")
    return label


@router.post("/scan/control-preview")
def preview_control_scan(
    payload: PayrollControlScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    return _control_preview(db, _load_control_scan(db, payload, current), payload.employee_id)


@router.post("/scan/control-confirm", response_model=PayrollRecordOut, status_code=201)
def confirm_control_scan(
    payload: PayrollControlConfirmIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    label = _load_control_scan(db, payload, current, for_update=False)
    if payload.review_token != _control_review_token(label, payload.employee_id):
        raise HTTPException(409, "Control QR or employee changed since review; scan the QR again")

    def validate_locked_label(locked_label: PayrollQrLabel) -> None:
        if payload.review_token != _control_review_token(locked_label, payload.employee_id):
            raise HTTPException(409, "Control QR or employee changed since review; scan the QR again")

    record, created = _create_record_from_payload(
        db,
        PayrollRecordIn(
            scan_uid=label.label_uid, employee_id=payload.employee_id,
            work=jsonable_encoder(_qr_label_scan_payload(label)), source="payroll_control_confirm",
        ),
        current=current,
        control_confirmed=True,
        issued_label_validator=validate_locked_label,
    )
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, duplicate=not created, employees=employees, departments=departments)


@router.post("/scan/numeric-work", response_model=PayrollNumericWorkScanOut, status_code=201)
def record_numeric_work_scan(
    payload: PayrollNumericWorkScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    normalized = payload.token.strip()
    if (
        len(normalized) != PAYROLL_QR_TOKEN_LENGTH
        or not normalized.isdigit()
        or not normalized.startswith(PAYROLL_WORK_TOKEN_PREFIX)
    ):
        raise HTTPException(400, "Payroll work QR token must contain exactly 9 digits and start with 2")

    factory_code = selected_factory_code(current)
    label = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.id == int(normalized[1:]),
        PayrollQrLabel.factory_code == factory_code,
    ).first()
    if not label:
        raise HTTPException(404, "Payroll work QR was not found")
    if label.status == "superseded":
        raise HTTPException(409, "This payroll QR was replaced by split labels and can no longer be scanned")

    employee = db.query(Employee).filter(
        Employee.id == payload.employee_id,
        Employee.factory_code == factory_code,
    ).first()
    if not employee:
        raise HTTPException(404, "Employee not found")

    work_payload = jsonable_encoder(_qr_label_scan_payload(label))
    if _is_control_operation(label):
        _assert_control_not_voided(db, label)
        return {"work": work_payload, "record": None, "control_preview": _control_preview(db, label, payload.employee_id)}
    employee_payload = _employee_scan_payload(
        employee,
        badge_id=employee.employee_no or _numeric_qr_token(PAYROLL_EMPLOYEE_TOKEN_PREFIX, int(employee.id)),
        source="milana_erp_numeric_work_scan",
        db=db,
    )
    record_input = PayrollRecordIn(
        scan_uid=label.label_uid,
        employee_id=int(employee.id),
        employee_user_id=employee.user_id,
        employee=employee_payload,
        work=work_payload,
        scanned_at=payload.scanned_at,
        source="payroll_scan",
    )
    record, created = _create_record_from_payload(db, record_input, current=current)
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return {
        "work": _qr_label_scan_payload(label),
        "record": _serialize_record(
            record,
            duplicate=not created,
            employees=employees,
            departments=departments,
        ),
    }


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
        return _qr_label_scan_payload(label)

    raise HTTPException(400, "Unknown payroll QR token type")


class _PayrollOrderLookup:
    """Targeted scalar lookups; shared order_reference code owns resolution rules.

    Bound IN lists to 400 values and never load unrelated order/alias history.
    Preparing original and canonical snapshot references takes two batch passes;
    subsequent canonical/variant resolution is entirely in memory.
    """

    def __init__(self, db, requests, snapshot_requests=()):
        self.orders = {"PO": {}, "SO": {}}
        self.references = {"PO": {}, "SO": {}}
        self.aliases_by_reference = {}
        self.aliases_by_entity = {}
        self.loaded_references = set()
        self.loaded_ids = {"PO": set(), "SO": set()}
        self._load(db, requests)
        variants = set()
        for namespace, reference, entity_id, production_id in snapshot_requests:
            try:
                canonical = canonical_order_reference(db, namespace, reference, entity_id=entity_id,
                                                      production_order_id=production_id, lookup=self)
            except HTTPException:
                # Defer errors to the original counts/serializer evaluation order.
                continue
            if canonical != reference:
                variants.add((namespace, canonical, entity_id, production_id))
        if variants:
            self._load(db, variants)
            variant_entities = {}

            def collect_alias_entities(namespaces, entity_id):
                variant_entities.setdefault(tuple(namespaces), set()).add(entity_id)
                return ()

            # Let the shared resolver choose the alias namespace/entity. Only
            # page snapshots need complete variants, not every global group.
            probe = SimpleNamespace(by_id=self.by_id, by_reference=self.by_reference,
                                    aliases=self.aliases, alias_references=collect_alias_entities)
            for namespace, reference, entity_id, production_id in variants:
                try:
                    order_reference_variants(db, namespace, reference, entity_id=entity_id,
                                             production_order_id=production_id, lookup=probe)
                except HTTPException:
                    continue  # Preserve the original point at which this fails.
            for namespaces, identities in variant_entities.items():
                for ids in self._chunks(identities):
                    self._add_aliases(db.query(BusinessOrderAlias).filter(
                        BusinessOrderAlias.namespace.in_(namespaces), BusinessOrderAlias.entity_id.in_(ids),
                    ).all())

    @staticmethod
    def _chunks(values):
        ordered = sorted(values)
        for start in range(0, len(ordered), 400):
            yield ordered[start:start + 400]

    def _add_aliases(self, rows):
        for row in rows:
            self.aliases_by_reference.setdefault((row.namespace, row.reference), {})[row.entity_id] = row
            self.aliases_by_entity.setdefault((row.namespace, row.entity_id), set()).add(row.reference)

    def _load(self, db, requests):
        references, production_ids, sales_ids = set(), set(), set()
        for namespace, reference, entity_id, production_id in requests:
            if reference:
                references.update((reference, reference.strip()))
            if entity_id is not None:
                (sales_ids if namespace == "SO" else production_ids).add(entity_id)
            if production_id is not None:
                production_ids.add(production_id)
        references -= self.loaded_references
        for chunk in self._chunks(references):
            aliases = db.query(BusinessOrderAlias).filter(
                BusinessOrderAlias.namespace.in_(["PO", "USL", "PUBLIC_PO", "SO"]),
                BusinessOrderAlias.reference.in_(chunk),
            ).all()
            self._add_aliases(aliases)
            for alias in aliases:
                (sales_ids if alias.namespace == "SO" else production_ids).add(alias.entity_id)

        self._load_orders(db, "PO", production_ids, references)
        sales_ids.update(row.sales_order_id for row in self.orders["PO"].values() if row.sales_order_id is not None)
        self._load_orders(db, "SO", sales_ids, references)
        for row in self.orders["PO"].values():
            row.sales_order = self.orders["SO"].get(row.sales_order_id)
            row.sales_order_no = row.sales_order.order_no if row.sales_order is not None else None
            row.order_no = ProductionOrder.order_no.fget(row)
        self.loaded_references.update(references)

    def _load_orders(self, db, namespace, ids, references):
        model = SalesOrder if namespace == "SO" else ProductionOrder
        column = model.order_no if namespace == "SO" else model.production_no
        columns = [model.id, column] if namespace == "SO" else [model.id, column, model.sales_order_id, model.source_type]
        missing_ids = ids - self.loaded_ids[namespace]
        id_chunks, reference_chunks = list(self._chunks(missing_ids)), list(self._chunks(references))
        for index in range(max(len(id_chunks), len(reference_chunks))):
            filters = []
            if index < len(id_chunks):
                filters.append(model.id.in_(id_chunks[index]))
            if index < len(reference_chunks):
                filters.append(column.in_(reference_chunks[index]))
            for result in db.query(*columns).filter(or_(*filters)).all():
                row = SimpleNamespace(**result._mapping)
                self.orders[namespace][row.id] = row
                self.references[namespace][getattr(row, column.key)] = row
        self.loaded_ids[namespace].update(missing_ids | self.orders[namespace].keys())

    def by_id(self, namespace, entity_id):
        row = self.orders["SO" if namespace == "SO" else "PO"].get(entity_id)
        return None if namespace == "USL" and row is not None and row.source_type != "usluga" else row

    def by_reference(self, namespace, reference):
        row = self.references["SO" if namespace == "SO" else "PO"].get(reference)
        return None if namespace == "USL" and row is not None and row.source_type != "usluga" else row

    def aliases(self, namespaces, reference):
        return [row for namespace in namespaces for row in self.aliases_by_reference.get((namespace, reference), {}).values()]

    def alias_references(self, namespaces, entity_id):
        return {reference for namespace in namespaces for reference in self.aliases_by_entity.get((namespace, entity_id), ())}


def _qr_label_order_lookup(db, count_rows, labels):
    requests, snapshots = set(), set()

    def collect(namespace, reference, *, entity_id=None, production_order_id=None):
        # Match the payroll wrapper's early return for empty, unlinked references.
        if reference or entity_id is not None:
            snapshots.add((namespace, reference, entity_id, production_order_id))
        return reference

    for row in count_rows:
        sales_no, production_no, sales_id, production_id = row[:4]
        requests.add(("SO", sales_no, sales_id, production_id))
        requests.add(("PO", production_no, production_id, None))
    for label in labels:
        requests.add(("SO", label.sales_order_no, label.sales_order_id, label.production_order_id))
        requests.add(("PO", label.production_no, label.production_order_id, None))
        _map_payroll_snapshot_references(label.payload, collect, production_order_id=label.production_order_id,
                                        sales_order_id=label.sales_order_id)
    return _PayrollOrderLookup(db, requests | snapshots, snapshots)


def _issue_order_lookup(db, rows):
    requests, snapshots = set(), set()

    def collect(namespace, reference, *, entity_id=None, production_order_id=None):
        if reference or entity_id is not None:
            snapshots.add((namespace, reference, entity_id, production_order_id))
        return reference

    for row in rows:
        requests.add(("PO", row.production_no, row.production_order_id, None))
        requests.add(("SO", row.sales_order_no, row.sales_order_id, row.production_order_id))
        _map_payroll_snapshot_references(
            row.payload,
            collect,
            production_order_id=row.production_order_id,
            sales_order_id=row.sales_order_id,
        )
    return _PayrollOrderLookup(db, requests | snapshots, snapshots)


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
            _payroll_order_reference_match(db, PayrollQrLabel.sales_order_no, "SO", pattern),
            _payroll_order_reference_match(db, PayrollQrLabel.production_no, "PO", pattern),
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
        variants = _payroll_order_reference_variants(db, exact_order)
        qry = qry.filter(or_(
            PayrollQrLabel.sales_order_no.in_(variants),
            PayrollQrLabel.production_no.in_(variants),
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
    # Aggregate the complete selected-factory ledger, independently of filters/page.
    count_columns = (PayrollQrLabel.sales_order_no, PayrollQrLabel.production_no,
                     PayrollQrLabel.sales_order_id, PayrollQrLabel.production_order_id)
    count_rows = db.query(*count_columns, func.count(PayrollQrLabel.id),
                         func.sum(case((PayrollQrLabel.status == "scanned", 1), else_=0))).filter(
        PayrollQrLabel.factory_code == selected_factory_code(current),
        PayrollQrLabel.status.in_(["available", "scanned"]),
    ).group_by(*count_columns).all()
    order_lookup = _qr_label_order_lookup(db, count_rows, labels)
    counts = {}
    for sales_no, production_no, sales_id, production_id, count, scanned in count_rows:
        key = (_canonical_payroll_reference(db, "SO", sales_no, entity_id=sales_id, production_order_id=production_id, lookup=order_lookup)
               or _canonical_payroll_reference(db, "PO", production_no, entity_id=production_id, lookup=order_lookup) or "No order")
        entry = counts.setdefault(key, {"order_no": key, "total": 0, "scanned": 0})
        entry["total"] += count
        entry["scanned"] += scanned
    return {
        "order_counts": list(counts.values()),
        "items": [
            _serialize_qr_label(label, records=records, employees=employees, departments=departments, order_lookup=order_lookup)
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
    label_snapshot = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.id == label_id,
        PayrollQrLabel.factory_code == factory_code,
    ).first()
    if not label_snapshot:
        raise HTTPException(404, "Payroll QR label not found")

    def find_record(label: PayrollQrLabel, *, for_update: bool) -> PayrollRecord | None:
        def first(query):
            if for_update:
                query = query.populate_existing().with_for_update()
            return query.first()

        linked = first(db.query(PayrollRecord).filter(
            PayrollRecord.id == label.payroll_record_id,
            PayrollRecord.factory_code == factory_code,
        )) if label.payroll_record_id else None
        if linked:
            return linked
        return first(db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid == label.label_uid,
        ))

    record_snapshot = find_record(label_snapshot, for_update=False)
    discovered_record_id = int(record_snapshot.id) if record_snapshot else None
    discovered_period_id = (
        int(record_snapshot.payroll_period_id)
        if record_snapshot and record_snapshot.payroll_period_id is not None
        else None
    )

    # Every period-bound payroll mutation uses period -> label -> record. An
    # initially periodless return never acquires a period after locking its
    # label; a concurrent new assignment must instead be retried.
    period = None
    if discovered_period_id is not None:
        period = (
            db.query(PayrollPeriod)
            .filter(
                PayrollPeriod.id == discovered_period_id,
                PayrollPeriod.factory_code == factory_code,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not period:
            raise HTTPException(409, "Payroll QR assignment changed; retry the return")

    label = (
        db.query(PayrollQrLabel)
        .filter(PayrollQrLabel.id == label_id, PayrollQrLabel.factory_code == factory_code)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    record = find_record(label, for_update=True)
    if not record:
        raise HTTPException(409, "This payroll QR is not assigned to an employee")
    if discovered_record_id is None or int(record.id) != discovered_record_id:
        raise HTTPException(409, "Payroll QR assignment changed; retry the return")
    current_period_id = int(record.payroll_period_id) if record.payroll_period_id is not None else None
    if current_period_id != discovered_period_id:
        raise HTTPException(409, "Payroll QR assignment changed; retry the return")
    if period and period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")
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


def _bulk_chunks(values, size=400):
    ordered = sorted(set(values))
    for start in range(0, len(ordered), size):
        yield ordered[start:start + size]


def _bulk_id_map(db: DbSession, model, values, *filters) -> dict[int, Any]:
    rows = []
    for chunk in _bulk_chunks(values):
        rows.extend(db.query(model).filter(model.id.in_(chunk), *filters).all())
    return {int(row.id): row for row in rows}


def _bulk_record_order_lookup(
    db: DbSession,
    prepared: list[dict[str, Any]],
    labels: dict[str, PayrollQrLabel],
):
    requests, snapshots = set(), set()

    def collect(namespace, reference, *, entity_id=None, production_order_id=None):
        if reference or entity_id is not None:
            snapshots.add((namespace, reference, entity_id, production_order_id))
        return reference

    for data in prepared:
        requests.add(("PO", data.get("production_no"), data.get("production_order_id"), None))
        requests.add((
            "SO", data.get("sales_order_no"), data.get("sales_order_id"), data.get("production_order_id"),
        ))
        _map_payroll_snapshot_references(
            data.get("raw_work_json"),
            collect,
            production_order_id=data.get("production_order_id"),
            sales_order_id=data.get("sales_order_id"),
        )
    for label in labels.values():
        requests.add(("PO", label.production_no, label.production_order_id, None))
        requests.add(("SO", label.sales_order_no, label.sales_order_id, label.production_order_id))
        _map_payroll_snapshot_references(
            label.payload,
            collect,
            production_order_id=label.production_order_id,
            sales_order_id=label.sales_order_id,
        )
    return _PayrollOrderLookup(db, requests | snapshots, snapshots)


def _bulk_validation_context(
    db: DbSession,
    prepared: list[dict[str, Any]],
    labels: dict[str, PayrollQrLabel],
    factory_code: str,
) -> dict[str, Any]:
    employee_ids = {int(data["employee_id"]) for data in prepared if data.get("employee_id")}
    employees = _bulk_id_map(db, Employee, employee_ids, Employee.factory_code == factory_code)
    user_ids = {int(data["employee_user_id"]) for data in prepared if data.get("employee_user_id")}
    user_ids.update(int(row.user_id) for row in employees.values() if row.user_id)
    work_order_ids = {int(data["work_order_id"]) for data in prepared if data.get("work_order_id")}
    work_orders = _bulk_id_map(db, WorkOrder, work_order_ids)
    order_lookup = _bulk_record_order_lookup(db, prepared, labels)
    production_ids = {int(data["production_order_id"]) for data in prepared if data.get("production_order_id")}
    production_ids.update(int(row.production_order_id) for row in work_orders.values())
    production_ids.update(int(identity) for identity in order_lookup.orders["PO"])
    production_orders = _bulk_id_map(db, ProductionOrder, production_ids)
    sales_order_ids = {int(data["sales_order_id"]) for data in prepared if data.get("sales_order_id")}
    sales_order_ids.update(
        int(row.sales_order_id) for row in production_orders.values() if row.sales_order_id is not None
    )
    batch_ids = {int(data["production_batch_id"]) for data in prepared if data.get("production_batch_id")}
    batch_ids.update(
        int(row.production_batch_id) for row in work_orders.values() if row.production_batch_id is not None
    )
    model_ids = {int(data["model_id"]) for data in prepared if data.get("model_id")}
    model_ids.update(int(row.model_id) for row in production_orders.values() if row.model_id is not None)
    factory_production_ids = set()
    for chunk in _bulk_chunks(production_ids):
        factory_production_ids.update(
            int(row[0])
            for row in db.query(ProductionOrder.id).filter(
                ProductionOrder.id.in_(chunk),
                production_order_factory_condition(factory_code),
            ).all()
        )
    return {
        "employees": employees,
        "users": _bulk_id_map(db, User, user_ids, User.factory_code == factory_code),
        "work_orders": work_orders,
        "production_orders": production_orders,
        "sales_orders": _bulk_id_map(db, SalesOrder, sales_order_ids),
        "production_batches": _bulk_id_map(db, ProductionBatch, batch_ids),
        "models": _bulk_id_map(db, Model, model_ids),
        "factory_production_ids": factory_production_ids,
        "order_lookup": order_lookup,
    }


def _prelock_bulk_record_resources(
    db: DbSession,
    payload: PayrollRecordBulkIn,
    factory_code: str,
) -> tuple[
    list[dict[str, Any]],
    list[PayrollPeriod | None],
    dict[str, PayrollQrLabel],
    dict[str, PayrollRecord],
    dict[str, Any],
]:
    prepared = [_prepare_record_data(row, payload.payroll_period_id) for row in payload.records]
    open_periods = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.factory_code == factory_code, PayrollPeriod.status == "open")
        .order_by(PayrollPeriod.id.desc())
        .all()
        if any(data.get("payroll_period_id") is None for data in prepared) else []
    )
    candidate_ids: list[int | None] = [
        int(data["payroll_period_id"]) if data.get("payroll_period_id") is not None else None
        for data in prepared
    ]
    pending = sorted(
        ((as_utc(data["scanned_at"]), index) for index, data in enumerate(prepared) if candidate_ids[index] is None),
        key=lambda row: row[0],
    )
    periods = sorted(
        ((as_utc(period.start_date), as_utc(period.end_date), int(period.id), period) for period in open_periods),
        key=lambda row: row[0],
    )
    active: list[tuple[int, datetime, Any]] = []
    period_index = 0
    for scanned_at, row_index in pending:
        while period_index < len(periods) and periods[period_index][0] <= scanned_at:
            start, end, period_id, period = periods[period_index]
            heapq.heappush(active, (-period_id, end, period))
            period_index += 1
        while active and active[0][1] < scanned_at:
            heapq.heappop(active)
        candidate_ids[row_index] = int(active[0][2].id) if active else None

    unique_period_ids = sorted({period_id for period_id in candidate_ids if period_id is not None})
    locked_period_rows = []
    for chunk in _bulk_chunks(unique_period_ids):
        locked_period_rows.extend(
            db.query(PayrollPeriod)
            .filter(
                PayrollPeriod.factory_code == factory_code,
                PayrollPeriod.id.in_(chunk),
            )
            .order_by(PayrollPeriod.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
    locked_periods = {int(period.id): period for period in locked_period_rows}

    scan_uids = sorted({data["scan_uid"] for data in prepared if data.get("scan_uid")})
    label_rows = []
    for chunk in _bulk_chunks(scan_uids):
        label_rows.extend(
            db.query(PayrollQrLabel)
            .filter(
                PayrollQrLabel.factory_code == factory_code,
                PayrollQrLabel.label_uid.in_(chunk),
            )
            .order_by(PayrollQrLabel.label_uid)
            .populate_existing()
            .with_for_update()
            .all()
        )
    labels = {label.label_uid: label for label in label_rows}
    existing_scan_records = {}
    for chunk in _bulk_chunks(scan_uids):
        for record in db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid.in_(chunk),
        ).all():
            existing_scan_records[record.scan_uid] = record
    rows_to_validate = [
        data for data in prepared
        if not data.get("scan_uid") or data["scan_uid"] not in existing_scan_records
    ]
    return (
        prepared,
        [locked_periods.get(period_id) if period_id is not None else None for period_id in candidate_ids],
        labels,
        existing_scan_records,
        _bulk_validation_context(db, rows_to_validate, labels, factory_code),
    )


@router.post("/records/bulk", response_model=PayrollBulkOut)
def create_records_bulk(
    payload: PayrollRecordBulkIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.scan", "payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    prepared, periods, labels, scan_records, validation_context = _prelock_bulk_record_resources(
        db, payload, factory_code,
    )
    dedupe_keys = set()
    new_scan_uids = set()
    for data, period in zip(prepared, periods):
        if data.get("scan_uid") and data["scan_uid"] in scan_records:
            existing = scan_records[data["scan_uid"]]
            if data.get("employee_id") and int(existing.employee_id) != int(data["employee_id"]):
                raise HTTPException(
                    409,
                    "This payroll work QR was already recorded for another employee; generate a separate payroll QR for another payable worker/unit",
                )
            continue
        if data.get("scan_uid") and data["scan_uid"] in new_scan_uids:
            # The first occurrence is validated and created before this row;
            # the later row must keep the historical duplicate-replay path.
            continue
        if data.get("scan_uid"):
            new_scan_uids.add(data["scan_uid"])
        if data.get("payroll_period_id") is not None and period is None:
            raise HTTPException(404, "Payroll period not found")
        _validate_and_enrich_record(
            db,
            data,
            factory_code,
            allow_manual_payable_values=_can_set_payable_values(current),
            locked_labels=labels,
            validation_context=validation_context,
        )
        if _is_control_operation(data):
            raise HTTPException(409, "Control operation requires review and confirmation before payroll is recorded")
        dedupe_keys.add(data["dedupe_key"])
    dedupe_records = {}
    for chunk in _bulk_chunks(dedupe_keys):
        for record in db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.dedupe_key.in_(chunk),
        ).all():
            dedupe_records[record.dedupe_key] = record

    records: list[PayrollRecord] = []
    created_count = 0
    duplicate_count = 0
    created_ids: list[int] = []
    duplicates: set[int] = set()
    for row, data, period in zip(payload.records, prepared, periods):
        record, created = _create_record_from_payload(
            db,
            row,
            current=current,
            period_id_override=payload.payroll_period_id,
            audit_individual=True,
            prepared_data=data,
            prelocked_period=period,
            locked_labels=labels,
            validation_context=validation_context,
            data_is_validated=True,
            known_scan_records=scan_records,
            known_dedupe_records=dedupe_records,
        )
        records.append(record)
        if created:
            created_count += 1
            created_ids.append(int(record.id))
            if record.scan_uid:
                scan_records[record.scan_uid] = record
            dedupe_records[record.dedupe_key] = record
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
    refreshed_records = {}
    for chunk in _bulk_chunks(int(record.id) for record in records):
        for record in (
            db.query(PayrollRecord)
            .filter(PayrollRecord.id.in_(chunk), PayrollRecord.factory_code == factory_code)
            .populate_existing()
            .all()
        ):
            refreshed_records[int(record.id)] = record
    records = [refreshed_records[int(record.id)] for record in records]
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
    ).first()
    if not record:
        raise HTTPException(404, "Payroll record not found")
    period = db.query(PayrollPeriod).filter(
        PayrollPeriod.id == record.payroll_period_id,
        PayrollPeriod.factory_code == factory_code,
    ).populate_existing().with_for_update().first() if record.payroll_period_id else None
    record = (
        db.query(PayrollRecord)
        .filter(PayrollRecord.id == record_id, PayrollRecord.factory_code == factory_code)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not record:
        raise HTTPException(404, "Payroll record not found")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll records can only be voided by an admin")
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
    ).first()
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
    if payload.target_period_id == record.payroll_period_id:
        raise HTTPException(409, "A reversal must be posted to a different editable payroll period")

    target_period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.id == payload.target_period_id,
            PayrollPeriod.factory_code == factory_code,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not target_period:
        raise HTTPException(404, "Target payroll period not found")
    _assert_period_accepts_adjustments(target_period)

    record = (
        db.query(PayrollRecord)
        .filter(PayrollRecord.id == record_id, PayrollRecord.factory_code == factory_code)
        .populate_existing()
        .with_for_update()
        .first()
    )
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
    ).filter(PayrollRecord.status != "voided").options(load_only(
        PayrollRecord.employee_id,
        PayrollRecord.currency,
        PayrollRecord.quantity,
        PayrollRecord.total_amount,
        PayrollRecord.operation_section,
        PayrollRecord.operation_code,
        PayrollRecord.operation_name,
    ))

    adjustment_qry = _filtered_adjustment_query(
        db,
        factory_code=factory_code,
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    ).options(load_only(
        PayrollAdjustment.employee_id,
        PayrollAdjustment.currency,
        PayrollAdjustment.adjustment_type,
        PayrollAdjustment.amount,
    ))

    employee_groups: dict[tuple[int, str], dict[str, Any]] = {}
    operation_groups: dict[tuple[int, str, str | None, str | None, str | None], dict[str, Any]] = {}
    employee_ids: set[int] = set()
    currencies: set[str] = set()
    records_count = 0
    adjustment_count = 0
    total_quantity = Decimal("0")
    piecework_amount = Decimal("0")
    bonus_amount = Decimal("0")
    deduction_amount = Decimal("0")

    def employee_group(employee_id_value: int, currency_value: str) -> dict[str, Any]:
        return employee_groups.setdefault(
            (int(employee_id_value), currency_value),
            {
                "employee_id": int(employee_id_value),
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

    # These reports can cover years of scans. Iterate in fixed-size fetch
    # batches and retain only the response's employee/operation aggregates.
    for record in base_qry.yield_per(400):
        record_employee_id = int(record.employee_id)
        record_currency = str(record.currency or "UZS")
        employee_ids.add(record_employee_id)
        currencies.add(record_currency)
        records_count += 1
        total_quantity += record.quantity or Decimal("0")
        piecework_amount += record.total_amount or Decimal("0")
        current = employee_group(record_employee_id, record_currency)
        current["records_count"] += 1
        current["quantity"] += record.quantity or Decimal("0")
        current["piecework_amount"] += record.total_amount or Decimal("0")
        current["total_amount"] += record.total_amount or Decimal("0")

        if group_by_operation:
            operation_key = (
                record_employee_id,
                record_currency,
                record.operation_section,
                record.operation_code,
                record.operation_name,
            )
            op = operation_groups.setdefault(
                operation_key,
                {
                    "employee_id": record_employee_id,
                    "operation_section": record.operation_section,
                    "operation_code": record.operation_code,
                    "operation_name": record.operation_name,
                    "currency": record_currency,
                    "records_count": 0,
                    "quantity": Decimal("0"),
                    "total_amount": Decimal("0"),
                },
            )
            op["records_count"] += 1
            op["quantity"] += record.quantity or Decimal("0")
            op["total_amount"] += record.total_amount or Decimal("0")

    for adjustment in adjustment_qry.yield_per(400):
        adjustment_employee_id = int(adjustment.employee_id)
        adjustment_currency = str(adjustment.currency or "UZS")
        employee_ids.add(adjustment_employee_id)
        currencies.add(adjustment_currency)
        adjustment_count += 1
        current = employee_group(adjustment_employee_id, adjustment_currency)
        signed_amount = _adjustment_signed_amount(adjustment)
        current["adjustment_count"] += 1
        current["adjustment_amount"] += signed_amount
        current["total_amount"] += signed_amount
        if adjustment.adjustment_type == "deduction":
            amount = adjustment.amount or Decimal("0")
            deduction_amount += amount
            current["deduction_amount"] += amount
        else:
            amount = adjustment.amount or Decimal("0")
            bonus_amount += amount
            current["bonus_amount"] += amount

    employees, departments = _load_employee_maps(db, employee_ids)
    for (group_employee_id, _currency), group in employee_groups.items():
        employee = employees.get(group_employee_id)
        department = (
            departments.get(int(employee.department_id))
            if employee and employee.department_id
            else None
        )
        group["employee_name"] = (
            employee.full_name if employee else f"Employee {group_employee_id}"
        )
        group["department_id"] = employee.department_id if employee else None
        group["department_name"] = department.name if department else None

    if group_by_operation:
        for key, op in operation_groups.items():
            employee_key = (key[0], key[1])
            employee_groups[employee_key]["operations"].append(PayrollSummaryOperationOut(**op))

    employees_out = [PayrollSummaryEmployeeOut(**row) for row in employee_groups.values()]
    employees_out.sort(key=lambda row: (str(row.employee_name).lower(), row.employee_id))
    summary_currency = (
        next(iter(currencies))
        if len(currencies) == 1
        else ("MIXED" if currencies else "UZS")
    )
    adjustment_amount = bonus_amount - deduction_amount
    total_amount = piecework_amount + adjustment_amount
    return PayrollSummaryOut(
        records_count=records_count,
        adjustment_count=adjustment_count,
        quantity=total_quantity,
        piecework_amount=piecework_amount,
        adjustment_amount=adjustment_amount,
        bonus_amount=bonus_amount,
        deduction_amount=deduction_amount,
        total_amount=total_amount,
        currency=summary_currency,
        employees=employees_out,
    )


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
    qry = _filtered_adjustment_query(
        db,
        factory_code=selected_factory_code(current),
        period_id=period_id,
        employee_id=employee_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = qry.order_by(None).count()
    ordered_qry = qry.order_by(PayrollAdjustment.id.desc())
    if total is None:
        return ordered_qry.all()
    rows = ordered_qry.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


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
    ).populate_existing().with_for_update().first() if payload.payroll_period_id else None
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


@router.delete("/adjustments/{adjustment_id}", status_code=204)
def delete_adjustment(
    adjustment_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "*")),
):
    factory_code = selected_factory_code(current)
    adjustment = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.id == adjustment_id,
        PayrollAdjustment.factory_code == factory_code,
    ).with_for_update().first()
    if not adjustment:
        raise HTTPException(404, "Payroll adjustment not found")
    if adjustment.source_payroll_record_id:
        raise HTTPException(409, "Linked payroll reversal adjustments cannot be deleted")
    if adjustment.payroll_period_id:
        period = db.query(PayrollPeriod).filter(
            PayrollPeriod.id == adjustment.payroll_period_id,
            PayrollPeriod.factory_code == factory_code,
        ).populate_existing().with_for_update().first()
        if not period:
            raise HTTPException(404, "Payroll period not found")
        _assert_period_accepts_adjustments(period)
    log_action(db, current, "delete", "PayrollAdjustment", adjustment.id, old_value={
        "factory_code": adjustment.factory_code,
        "employee_id": adjustment.employee_id,
        "payroll_period_id": adjustment.payroll_period_id,
        "adjustment_type": adjustment.adjustment_type,
        "amount": adjustment.amount,
        "signed_amount": _adjustment_signed_amount(adjustment),
        "currency": adjustment.currency,
        "reason": adjustment.reason,
    })
    db.delete(adjustment)
    db.commit()
    return Response(status_code=204)

