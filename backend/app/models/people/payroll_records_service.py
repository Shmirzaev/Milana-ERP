"""Payroll accrual checks and one request commit; persistence uses the supplied Session."""
from __future__ import annotations
from app.schemas.people.payroll_qr_persistence import apply_payroll_qr_changes
from app.schemas.people.payroll_record_persistence import apply_payroll_record_changes, build_split_payroll_qr_label, add_split_payroll_qr_row
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import uuid4
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_
from app.core.deps import is_admin
from app.core.dt import as_utc, utcnow
from app.schemas import Employee, Model, PayrollPeriod, PayrollQrLabel, PayrollRecord, ProductionBatch, ProductionOrder, SalesOrder, User, WorkOrder
from app.libs.dto.people.payroll import PayrollControlScanIn, PayrollControlConfirmIn, PayrollNumericWorkScanIn, PayrollRecordBulkIn, PayrollRecordIn, PayrollScanSplitIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_factory_scope_service import production_order_factory_condition
from app.models.employee_aliases_service import merged_employee
from app.models.payroll_operation_service import is_control_operation as _is_control_operation
from app.models.people.payroll_service import PAYROLL_EMPLOYEE_TOKEN_PREFIX, PAYROLL_QR_TOKEN_LENGTH, PAYROLL_WORK_TOKEN_PREFIX, _PayrollOrderLookup, _employee_scan_payload, _map_payroll_snapshot_references, _numeric_qr_token, _qr_label_scan_payload, _serialize_qr_label, or_
from app.models.people.payroll_service import MUTATION_LOCKED_PERIOD_STATUSES, _canonicalize_payroll_input, _to_decimal
from datetime import datetime, time
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.core.deps import is_admin, user_permissions
from app.core.dt import as_utc, utcnow
from app.core.order_reference import order_reference_variants
from app.schemas import Employee, Model, PayrollPeriod, PayrollQrLabel, PayrollRecord, ProductionBatch, ProductionOrder, SalesOrder, User, WorkOrder
from app.libs.dto.people.payroll import PayrollRecordIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_factory_scope_service import require_production_order_factory, require_work_order_factory
from app.models.employee_aliases_service import merged_employee
from app.models.payroll_operation_service import is_control_operation as _is_control_operation
from app.models.people.payroll_service import _canonical_payroll_reference as _canonical_payroll_reference, _canonical_payroll_snapshot as _canonical_payroll_snapshot, _dget as _dget, _load_employee_maps as _load_employee_maps, _normalize_production_batch_no as _normalize_production_batch_no, _present as _present, _serialize_record as _serialize_record, _to_int as _to_int, _to_text as _to_text
from sqlalchemy.orm import Session
from app.schemas.people.payroll_record_persistence import insert_payroll_record, add_scanned_payroll_label, apply_scanned_payroll_label

MAX_PAYROLL_SNAPSHOT_BYTES = 16 * 1024

MAX_PAYROLL_SNAPSHOT_DEPTH = 16


PAYROLL_RECORD_COMPONENT_MAX = Decimal("9999999999.9999")

PAYROLL_RECORD_TOTAL_MAX = Decimal("999999999999.99")

PAYROLL_WORK_UNITS = {"piece", "work_unit"}

_PERIOD_NOT_PRELOCKED = object()



def _assert_record_numeric_components(quantity: Decimal, rate: Decimal) -> None:
    if quantity > PAYROLL_RECORD_COMPONENT_MAX:
        raise HTTPException(400, "Payroll quantity exceeds the supported maximum of 9999999999.9999")
    if rate > PAYROLL_RECORD_COMPONENT_MAX:
        raise HTTPException(400, "Payroll rate exceeds the supported maximum of 9999999999.9999")


def _validated_record_total_amount(quantity: Decimal, rate: Decimal) -> Decimal:
    _assert_record_numeric_components(quantity, rate)
    total = (quantity * rate).quantize(Decimal("0.01"))
    if total > PAYROLL_RECORD_TOTAL_MAX:
        raise HTTPException(400, "Payroll total exceeds the supported maximum of 999999999999.99")
    return total


def _compact_field(value: str | None) -> str | None:
    text = _to_text(value)
    if text in (None, "-"):
        return None
    return text


def _compact_number(value: str | None) -> int | None:
    return _to_int(_compact_field(value))




def _legacy_payroll_dedupe_keys(db, data: dict[str, Any]) -> set[str]:
    # Existing hashes are immutable. Recreate candidates from this retry's exact
    # numeric/time values, varying only the mapped order names (not DB decimals).
    production_refs = order_reference_variants(db, "PO", data.get("production_no"), entity_id=data.get("production_order_id")) | {data.get("production_no")}
    sales_refs = order_reference_variants(db, "SO", data.get("sales_order_no"), entity_id=data.get("sales_order_id"), production_order_id=data.get("production_order_id")) | {data.get("sales_order_no")}
    return {
        _dedupe_key({**data, "production_no": production_no, "sales_order_no": sales_no})
        for production_no in production_refs for sales_no in sales_refs
    }


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


def _validate_payroll_snapshot(value: dict[str, Any], field: str) -> dict[str, Any]:
    """Bound persisted raw JSON without closing its legacy/open key space."""
    minimum_size = 2  # The root object braces.
    pending = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, dict):
            if depth > MAX_PAYROLL_SNAPSHOT_DEPTH:
                raise HTTPException(422, f"{field} snapshot exceeds maximum nesting depth")
            if len(current) > MAX_PAYROLL_SNAPSHOT_BYTES // 4:
                raise HTTPException(422, f"{field} snapshot exceeds maximum size of {MAX_PAYROLL_SNAPSHOT_BYTES} bytes")
            for index, (key, child) in enumerate(current.items()):
                child_minimum = len(child) + 2 if isinstance(child, str) else 2 if isinstance(child, (dict, list)) else 1
                minimum_size += (1 if index else 0) + len(key) + 3 + child_minimum
                if minimum_size > MAX_PAYROLL_SNAPSHOT_BYTES:
                    raise HTTPException(422, f"{field} snapshot exceeds maximum size of {MAX_PAYROLL_SNAPSHOT_BYTES} bytes")
                if isinstance(child, (dict, list)):
                    pending.append((child, depth + 1))
        elif isinstance(current, list):
            if depth > MAX_PAYROLL_SNAPSHOT_DEPTH:
                raise HTTPException(422, f"{field} snapshot exceeds maximum nesting depth")
            if len(current) > MAX_PAYROLL_SNAPSHOT_BYTES // 2:
                raise HTTPException(422, f"{field} snapshot exceeds maximum size of {MAX_PAYROLL_SNAPSHOT_BYTES} bytes")
            for index, child in enumerate(current):
                child_minimum = len(child) + 2 if isinstance(child, str) else 2 if isinstance(child, (dict, list)) else 1
                minimum_size += (1 if index else 0) + child_minimum
                if minimum_size > MAX_PAYROLL_SNAPSHOT_BYTES:
                    raise HTTPException(422, f"{field} snapshot exceeds maximum size of {MAX_PAYROLL_SNAPSHOT_BYTES} bytes")
                if isinstance(child, (dict, list)):
                    pending.append((child, depth + 1))

    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        size_bytes = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise HTTPException(422, f"{field} snapshot must contain finite JSON values") from exc
    if size_bytes > MAX_PAYROLL_SNAPSHOT_BYTES:
        raise HTTPException(422, f"{field} snapshot exceeds maximum size of {MAX_PAYROLL_SNAPSHOT_BYTES} bytes")
    return value


def _extra(payload: PayrollRecordIn, key: str) -> Any:
    return (payload.model_extra or {}).get(key)


def _first(*values: Any) -> Any:
    for value in values:
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

    employee_payload = _validate_payroll_snapshot(employee_payload, "employee")
    work_payload = _validate_payroll_snapshot(work_payload, "work")

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


def _can_period_override(user: User) -> bool:
    perms = user_permissions(user)
    return is_admin(user) or "management.approve" in perms or "payroll.approve" in perms


def _can_set_payable_values(user: User) -> bool:
    return is_admin(user) or "payroll.manage" in user_permissions(user)


def _find_period(
    db: Session,
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
    db: Session,
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
    db: Session,
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
        employee = merged_employee(db, factory_code, employee_id=employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    if employee.status == "archived":
        raise HTTPException(404, "Employee not found")
    data["employee_id"] = employee.id
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
        issued_label = locked_labels.get(data["scan_uid"]) if locked_labels is not None else (
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

    # Canonical references and trusted label enrichment change these snapshots.
    # Validate the final values before creating a record.
    data["raw_employee_json"] = _validate_payroll_snapshot(data.get("raw_employee_json") or {}, "employee") or None
    data["raw_work_json"] = _validate_payroll_snapshot(data.get("raw_work_json") or {}, "work") or None

    data["total_amount"] = _validated_record_total_amount(data["quantity"], data["rate_per_piece"])
    data["factory_code"] = factory_code
    data["operation_name"] = data.get("operation_name") or data.get("operation_code") or data.get("operation_section")
    data["dedupe_key"] = _dedupe_key(data)
    return data


def _mark_qr_label_scanned(
    db: Session,
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
        label = add_scanned_payroll_label(db, record=record, label_uid=label_uid)
    values = {
        'payload': label.payload or None,
        'production_order_id': data.get('production_order_id'),
        'sales_order_id': data.get('sales_order_id'),
        'work_order_id': data.get('work_order_id'),
        'production_batch_id': data.get('production_batch_id'),
        'model_id': data.get('model_id'),
        'production_no': data.get('production_no'),
        'sales_order_no': data.get('sales_order_no'),
        'batch_no': _normalize_production_batch_no(data.get('batch_no')),
        'model_code': data.get('model_code'),
        'operation_section': data.get('operation_section'),
        'operation_code': data.get('operation_code'),
        'operation_name': data.get('operation_name'),
        'sewing_flow_id': _to_int(raw_work.get('sewing_flow_id')),
        'sewing_line_code': _to_text(raw_work.get('sewing_line_code')),
        'sewing_line_name': _to_text(raw_work.get('sewing_line_name')),
        'cutting_passport_id': _to_int(raw_work.get('cutting_passport_id')),
        'cutting_passport_no': _to_text(raw_work.get('cutting_passport_no')),
        'size': _to_text(raw_work.get('size')),
        'copy_index': _to_int(raw_work.get('copy_index')) or 1,
        'quantity': data.get('quantity') or Decimal('0'),
        'rate_per_piece': data.get('rate_per_piece') or Decimal('0'),
        'currency': data.get('currency') or 'UZS',
        'status': 'scanned',
        'payroll_record_id': record.id,
        'last_scanned_at': record.scanned_at,
        'returned_at': None,
        'returned_by': None,
    }
    apply_scanned_payroll_label(db, label, values)


def _prepare_record_data(payload: PayrollRecordIn, period_id_override: int | None) -> dict[str, Any]:
    data = _normalize_record_payload(payload)
    if payload.work_date is not None:
        today = utcnow().astimezone(ZoneInfo("Asia/Tashkent")).date()
        if payload.work_date > today:
            raise HTTPException(400, "Payroll work date cannot be in the future")
        data["scanned_at"] = as_utc(datetime.combine(payload.work_date, time(12), ZoneInfo("Asia/Tashkent")))
    payload_period_id = payload.payroll_period_id or _to_int(_extra(payload, "payrollPeriodId"))
    if period_id_override is not None and data.get("payroll_period_id") is None:
        data["payroll_period_id"] = period_id_override
    else:
        data["payroll_period_id"] = payload_period_id
    return data


def _record_period_candidate(
    db: Session, payload: PayrollRecordIn, data: dict[str, Any], factory_code: str, *,
    for_update: bool, preserve_unassigned_period: bool = False,
) -> PayrollPeriod | None:
    if payload.work_date is not None:
        query = db.query(PayrollPeriod).filter(
            PayrollPeriod.factory_code == factory_code,
            PayrollPeriod.start_date <= data["scanned_at"],
            PayrollPeriod.end_date >= data["scanned_at"],
        ).order_by(PayrollPeriod.id)
        if for_update:
            query = query.populate_existing().with_for_update()
        periods = query.all()
        if len(periods) > 1:
            conflicts = ", ".join(f"{period.period_no} ({period.status})" for period in periods)
            raise HTTPException(
                409, f"Payroll work date matches overlapping periods: {conflicts}; resolve the periods first",
            )
        return periods[0] if periods else None
    if preserve_unassigned_period and not data.get("payroll_period_id"):
        return None
    if for_update:
        return _attach_period(db, data.get("payroll_period_id"), data["scanned_at"], factory_code)
    return _find_period(db, data.get("payroll_period_id"), data["scanned_at"], factory_code, for_update=False)


def _create_record_from_payload(
    db: Session,
    payload: PayrollRecordIn,
    *,
    current: User,
    period_id_override: int | None = None,
    audit_individual: bool = True,
    control_confirmed: bool = False,
    preserve_unassigned_period: bool = False,
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
                alias = merged_employee(db, factory_code, employee_id=data["employee_id"])
                if alias:
                    data["employee_id"] = alias.id
            if data.get("employee_id") and int(existing.employee_id) != int(data["employee_id"]):
                raise HTTPException(
                    409,
                    "This payroll work QR was already recorded for another employee; generate a separate payroll QR for another payable worker/unit",
                )
            return existing, False

    # Every new write acquires period -> label -> record locks.
    period = (
        _record_period_candidate(db, payload, data, factory_code, for_update=True,
                                 preserve_unassigned_period=preserve_unassigned_period)
        if prelocked_period is _PERIOD_NOT_PRELOCKED else prelocked_period
    )
    if data.get("payroll_period_id") and period is None:
        if payload.work_date is not None:
            raise HTTPException(409, "Payroll period does not contain the selected work date")
        raise HTTPException(404, "Payroll period not found")
    if not data_is_validated:
        data = _validate_and_enrich_record(
            db, data, factory_code,
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

    if payload.work_date is not None:
        if data.get("payroll_period_id") and (not period or period.id != data["payroll_period_id"]):
            raise HTTPException(409, "Payroll period does not contain the selected work date")
        if period and period.status != "open":
            raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")
    _assert_period_accepts_records(period, current)
    data["payroll_period_id"] = period.id if period else None

    record = insert_payroll_record(db, factory_code=factory_code, actor_id=current.id,
                                   data=data, status="recorded")
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


def create_record(
    payload: PayrollRecordIn,
    db: Session,
    current: User,
):
    record, created = _create_record_from_payload(db, payload, current=current)
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, duplicate=not created, employees=employees, departments=departments)


def _control_review_token(label: PayrollQrLabel, employee_id: int) -> str:
    snapshot = _qr_label_scan_payload(label)
    snapshot.pop("label_status", None)  # Successful confirmation/retry keeps its identity.
    snapshot.update(factory_code=label.factory_code, employee_id=employee_id, return_count=label.return_count)
    return hashlib.sha256(json.dumps(jsonable_encoder(snapshot), sort_keys=True).encode()).hexdigest()


def _control_label_query(db: Session, label: PayrollQrLabel):
    # Exact context prevents a manual order or another size/factory leaking into review.
    query = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == label.factory_code,
        PayrollQrLabel.status != "superseded",
        PayrollQrLabel.size == label.size,
        PayrollQrLabel.model_id == label.model_id,
        PayrollQrLabel.production_batch_id == label.production_batch_id,
        PayrollQrLabel.sewing_flow_id == label.sewing_flow_id,
        PayrollQrLabel.cutting_passport_id == label.cutting_passport_id,
        PayrollQrLabel.batch_no == label.batch_no,
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
    return query


def _control_preview(db: Session, label: PayrollQrLabel, employee_id: int) -> dict[str, Any]:
    labels = _control_label_query(db, label).order_by(PayrollQrLabel.id).all()
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


def _assert_control_not_voided(db: Session, label: PayrollQrLabel) -> None:
    voided = db.query(PayrollRecord.id).filter(
        PayrollRecord.factory_code == label.factory_code,
        PayrollRecord.status == "voided",
        or_(PayrollRecord.id == label.payroll_record_id, PayrollRecord.scan_uid == label.label_uid),
    ).first()
    if voided:
        raise HTTPException(409, "This Control payroll record was cancelled; return the QR before scanning it again")


def _load_control_scan(
    db: Session,
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
        Employee.id == payload.employee_id, Employee.factory_code == factory_code, Employee.status != "archived",
    ).first():
        raise HTTPException(404, "Employee not found")
    return label


def _prelock_bulk_record_resources(
    db: Session,
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
    # Discover candidates once, then retain the existing sorted period -> label
    # locks with populate_existing. Explicit work dates never fall back to an
    # unrelated open period and overlapping date ranges still reject the batch.
    requested_ids = {data["payroll_period_id"] for data in prepared if data.get("payroll_period_id")}
    dates = [data["scanned_at"] for data in prepared]
    filters = [PayrollPeriod.id.in_(requested_ids)]
    if dates:
        filters.append((PayrollPeriod.start_date <= max(dates)) & (PayrollPeriod.end_date >= min(dates)))
    candidates = db.query(PayrollPeriod).filter(
        PayrollPeriod.factory_code == factory_code, or_(*filters),
    ).order_by(PayrollPeriod.id.desc()).all()
    by_id = {period.id: period for period in candidates}
    candidate_ids = []
    for row, data in zip(payload.records, prepared):
        if row.work_date is not None:
            matches = [period for period in candidates
                       if as_utc(period.start_date) <= data["scanned_at"] <= as_utc(period.end_date)]
            if len(matches) > 1:
                raise HTTPException(409, "Payroll work date matches overlapping periods; resolve the periods first")
            candidate = matches[0] if matches else None
        elif data.get("payroll_period_id"):
            candidate = by_id.get(data["payroll_period_id"])
        else:
            candidate = next((period for period in candidates if period.status == "open"
                              and as_utc(period.start_date) <= data["scanned_at"] <= as_utc(period.end_date)), None)
        candidate_ids.append(int(candidate.id) if candidate else None)

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


def _bulk_chunks(values, size=400):
    ordered = sorted(set(values))
    for start in range(0, len(ordered), size):
        yield ordered[start:start + size]


def _bulk_id_map(db: Session, model, values, *filters) -> dict[int, Any]:
    rows = []
    for chunk in _bulk_chunks(values):
        rows.extend(db.query(model).filter(model.id.in_(chunk), *filters).all())
    return {int(row.id): row for row in rows}


def _bulk_record_order_lookup(
    db: Session,
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
    db: Session,
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


def preview_control_scan(payload: PayrollControlScanIn, db: Session, current: User):
    return _control_preview(db, _load_control_scan(db, payload, current), payload.employee_id)



def confirm_control_scan(payload: PayrollControlConfirmIn, db: Session, current: User):
    label = _load_control_scan(db, payload, current, for_update=False)
    reason = (payload.closure_reason or "").strip()
    if payload.close_unscanned and not reason:
        raise HTTPException(422, "Enter a reason for closing unscanned QRs")
    if payload.review_token != _control_review_token(label, payload.employee_id):
        raise HTTPException(409, "Control QR or employee changed since review; scan the QR again")

    def validate_locked_label(locked_label: PayrollQrLabel) -> None:
        if payload.review_token != _control_review_token(locked_label, payload.employee_id):
            raise HTTPException(409, "Control QR or employee changed since review; scan the QR again")

    record_payload = PayrollRecordIn(
        scan_uid=label.label_uid, employee_id=payload.employee_id,
        work_date=payload.work_date,
        work=jsonable_encoder(_qr_label_scan_payload(label)), source="payroll_control_confirm",
    )
    # Match the ledger's period -> labels -> records lock order. Lock the whole
    # reviewed group in stable order before confirming or closing any label.
    period = _record_period_candidate(db, record_payload, _prepare_record_data(record_payload, None),
                                      selected_factory_code(current), for_update=True)
    labels = _control_label_query(db, label).order_by(PayrollQrLabel.id).populate_existing().with_for_update().all()
    locked_labels = {row.label_uid: row for row in labels}
    if label.label_uid not in locked_labels:
        raise HTTPException(409, "Control QR changed since review; scan the QR again")
    validate_locked_label(locked_labels[label.label_uid])
    record, created = _create_record_from_payload(
        db, record_payload,
        current=current, control_confirmed=True, issued_label_validator=validate_locked_label,
        prelocked_period=period, locked_labels=locked_labels,
    )
    if payload.close_unscanned and not label.closure_details:
        if record.status == "voided":
            raise HTTPException(409, "Cancelled Control cannot close scanning")
        details = {"control_label_uid": label.label_uid, "closed_by": current.id,
                   "closed_at": utcnow().isoformat(), "reason": reason}
        closed_ids = []
        for row in labels:
            if row.status == "available" and not row.payroll_record_id:
                apply_payroll_qr_changes(row, {'status': "closed"})
                apply_payroll_qr_changes(row, {'closure_details': details})
                closed_ids.append(row.id)
        apply_payroll_qr_changes(label, {'closure_details': {**details, "closed_label_ids": closed_ids}})
        log_action(db, current, "close_unscanned_qrs", "PayrollQrLabel", label.id,
                   new_value=label.closure_details)
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, duplicate=not created, employees=employees, departments=departments)



def record_numeric_work_scan(payload: PayrollNumericWorkScanIn, db: Session, current: User):
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
        employee = merged_employee(db, factory_code, employee_id=payload.employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")

    if employee.status == "archived":
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
        work_date=payload.work_date,
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



def create_records_bulk(payload: PayrollRecordBulkIn, db: Session, current: User):
    factory_code = selected_factory_code(current)
    prepared, periods, labels, scan_records, validation_context = _prelock_bulk_record_resources(
        db, payload, factory_code,
    )
    dedupe_keys = set()
    new_scan_uids = set()
    for row, data, period in zip(payload.records, prepared, periods):
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
            if row.work_date is not None:
                raise HTTPException(409, "Payroll period does not contain the selected work date")
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



def split_scanned_record(record_id: int, payload: PayrollScanSplitIn, db: Session, current: User):
    factory = selected_factory_code(current)
    snapshot = db.query(PayrollRecord).filter(
        PayrollRecord.id == record_id, PayrollRecord.factory_code == factory,
    ).first()
    if not snapshot:
        raise HTTPException(404, "Issued payroll QR record not found")
    discovered_period_id = snapshot.payroll_period_id
    # Prelock every relevant period in stable order before label and record.
    date_periods = db.query(PayrollPeriod).filter(
        PayrollPeriod.factory_code == factory,
        or_(PayrollPeriod.id == discovered_period_id,
            (PayrollPeriod.start_date <= snapshot.scanned_at) & (PayrollPeriod.end_date >= snapshot.scanned_at)),
    ).order_by(PayrollPeriod.id).populate_existing().with_for_update().all()
    period = next((row for row in date_periods if row.id == discovered_period_id), None)
    label = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.payroll_record_id == record_id,
        PayrollQrLabel.factory_code == factory,
    ).with_for_update().populate_existing().first()
    record = db.query(PayrollRecord).filter(
        PayrollRecord.id == record_id, PayrollRecord.factory_code == factory,
    ).with_for_update().populate_existing().first()
    if not record or not label:
        raise HTTPException(404, "Issued payroll QR record not found")
    if record.payroll_period_id != discovered_period_id:
        raise HTTPException(409, "Payroll QR assignment changed; retry the split")
    children = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.split_from_label_id == label.id,
        PayrollQrLabel.factory_code == factory,
    ).order_by(PayrollQrLabel.id).all()
    if label.status == "superseded" and record.status == "voided" and children:
        records = [db.get(PayrollRecord, child.payroll_record_id) if child.payroll_record_id else None for child in children]
        if (len(records) != len(payload.parts) or any(
            not row or row.status != "recorded" or row.employee_id != part.employee_id or row.quantity != part.quantity
            for row, part in zip(records, payload.parts)
        )):
            raise HTTPException(409, "This QR has already been split with different allocations")
    else:
        if record.status != "recorded" or label.status != "scanned":
            raise HTTPException(409, "Only recorded, unpaid QR work can be split")
        if sum(part.quantity for part in payload.parts) != record.quantity or label.quantity != record.quantity:
            raise HTTPException(409, "Split pieces must equal the original QR quantity")
        if period and period.status != "open":
            raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")
        if any(p.status != "open" for p in date_periods):
            raise HTTPException(409, "The payroll period for this work date is no longer open")
        employee_ids = {part.employee_id for part in payload.parts}
        employees = db.query(Employee).filter(Employee.id.in_(employee_ids), Employee.factory_code == factory, Employee.status == "active").all()
        if {employee.id for employee in employees} != employee_ids:
            raise HTTPException(409, "Select active employees from this payroll factory")
        fields = (
            "production_order_id", "sales_order_id", "work_order_id", "production_batch_id", "model_id",
            "production_no", "sales_order_no", "batch_no", "model_code", "operation_section", "operation_code",
            "operation_name", "sewing_flow_id", "sewing_line_code", "sewing_line_name", "cutting_passport_id",
            "cutting_passport_no", "size", "rate_per_piece", "currency", "copy_index",
        )
        records = []
        for part in payload.parts:
            child = build_split_payroll_qr_label(
                **{field: getattr(label, field) for field in fields}, factory_code=factory,
                label_uid=f"OERP-SPLIT-{uuid4().hex.upper()}", split_from_label_id=label.id,
                quantity=Decimal(part.quantity), status="available", issued_by=current.id, issued_at=utcnow(),
            )
            add_split_payroll_qr_row(db, child)
            db.flush()
            row, _ = _create_record_from_payload(db, PayrollRecordIn(
                scan_uid=child.label_uid, employee_id=part.employee_id,
                work=jsonable_encoder(_qr_label_scan_payload(child)), scanned_at=record.scanned_at,
                payroll_period_id=record.payroll_period_id, source="payroll_scan_split",
            ), current=current, control_confirmed=True, preserve_unassigned_period=True, prelocked_period=period)
            # Preserve an unassigned source date as well as explicitly assigned periods.
            apply_payroll_record_changes(row, {'payroll_period_id': record.payroll_period_id})
            records.append(row)
        # Rounding is allocated once so a split never increases or loses salary.
        apply_payroll_record_changes(records[-1], {'total_amount': records[-1].total_amount + (record.total_amount - sum(row.total_amount for row in records))})
        if records[-1].total_amount < 0:
            raise HTTPException(409, "These quantities cannot preserve the original rounded payroll amount")
        apply_payroll_record_changes(record, {'status': "voided"})
        apply_payroll_qr_changes(label, {'status': "superseded"})
        apply_payroll_qr_changes(label, {'superseded_at': utcnow()})
        apply_payroll_qr_changes(label, {'superseded_by': current.id})
        log_action(db, current, "split_scanned_qr", "PayrollRecord", record.id,
                   old_value={"employee_id": record.employee_id, "quantity": record.quantity, "total_amount": record.total_amount},
                   new_value={"record_ids": [row.id for row in records], "parts": payload.model_dump()["parts"]})
    employees, departments = _load_employee_maps(db, {int(row.employee_id) for row in records})
    db.flush()
    for row in records:
        db.refresh(row)
    result = [_serialize_record(row, employees=employees, departments=departments) for row in records]
    db.commit()
    return result



def void_record(record_id: int, db: Session, current: User):
    factory_code = selected_factory_code(current)
    record = db.query(PayrollRecord).filter(
        PayrollRecord.id == record_id,
        PayrollRecord.factory_code == factory_code,
    ).first()
    if not record:
        raise HTTPException(404, "Payroll record not found")
    discovered_period_id = record.payroll_period_id
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
    if record.payroll_period_id != discovered_period_id:
        raise HTTPException(409, "Payroll record assignment changed; retry the void")
    if record.status == "paid" and not is_admin(current):
        raise HTTPException(409, "Paid payroll records can only be voided by an admin")
    if period and period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")
    old_status = record.status
    apply_payroll_record_changes(record, {'status': "voided"})
    log_action(db, current, "void", "PayrollRecord", record.id, old_value={"status": old_status}, new_value={"status": record.status})
    db.commit()
    db.refresh(record)
    employees, departments = _load_employee_maps(db, {int(record.employee_id)})
    return _serialize_record(record, employees=employees, departments=departments)



def return_qr_label(label_id: int, db: Session, current: User, expected_record_id: int | None=None):
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
    if label.status == "superseded":
        raise HTTPException(409, "A split original QR cannot be returned or scanned again")
    record = find_record(label, for_update=True)
    if not record:
        raise HTTPException(409, "This payroll QR is not assigned to an employee")
    if expected_record_id is not None and record.id != expected_record_id:
        raise HTTPException(409, "Payroll QR assignment changed; retry the return")
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
    apply_payroll_record_changes(record, {'original_scan_uid': original_uid})
    apply_payroll_record_changes(record, {'scan_uid': None})
    apply_payroll_record_changes(record, {'status': "voided"})
    apply_payroll_qr_changes(label, {'status': "available"})
    apply_payroll_qr_changes(label, {'payroll_record_id': None})
    apply_payroll_qr_changes(label, {'returned_at': utcnow()})
    apply_payroll_qr_changes(label, {'returned_by': current.id})
    apply_payroll_qr_changes(label, {'return_count': int(label.return_count or 0) + 1})
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
