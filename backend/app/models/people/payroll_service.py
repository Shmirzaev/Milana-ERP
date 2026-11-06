"""Payroll operations with explicit actor, Session, business checks and transaction ownership."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import or_
from app.core.dt import as_utc, utcnow
from app.core.order_reference import (
    order_reference_variants, resolve_order_id,
)
from app.schemas import (
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
from app.libs.dto.people.payroll import (
    PayrollAdjustmentOut,
    PayrollPeriodIn,
    PayrollPeriodUpdate,
    PayrollSummaryOut,
)
from app.models.process_qr_export_service import ProcessQrExportIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_factory_scope_service import require_production_order_factory
from app.models.payroll_reports_service import ReportLanguage
from app.models.employee_aliases_service import merged_employee
from app.models.payroll_operation_service import is_control_operation as _is_control_operation
from sqlalchemy import String, cast, func
from app.schemas import Department
from sqlalchemy import and_
from sqlalchemy.orm import load_only
from app.libs.dto.people.payroll import PayrollSummaryEmployeeOut, PayrollSummaryOperationOut
from types import SimpleNamespace
from sqlalchemy import case
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.core.order_reference import canonical_order_reference
from app.schemas.order_reference import BusinessOrderAlias
from sqlalchemy.orm import object_session
from app.models.process_qr_export_service import build_process_qr_xlsx
from app.models.factory_scope_service import require_factory_access
from app.models.payroll_reports_service import build_sewing_production_report_xlsx, build_sewing_salary_summary_xlsx
from sqlalchemy import Date
from app.schemas import SewingRecord
from app.models.payroll_reports_service import salary_report_days
from app.schemas import Bundle
from app.models.paid_operations_service import filter_operation_rows, paid_operations_from_details
from app.core.order_reference import order_reference_contains
from app.schemas.people.payroll import apply_payroll_period_changes, update_period_record_status


from sqlalchemy.orm import Session

from app.models.payroll_period_lock_service import lock_period_schedule as _lock_period_schedule
from app.schemas.people.payroll import add_payroll_period

PERIOD_CREATE_STATUSES = {"draft", "open"}


def _period_no_for(db: Session, start_date: datetime, factory_code: str) -> str:
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


def _assert_period_dates_available(
    db: Session, factory_code: str, start_date: datetime, end_date: datetime,
    *, exclude_id: int | None = None,
) -> None:
    # Match the scanner's inclusive bounds and all statuses. Ignoring a locked
    # period here would allow a new period to bypass its accounting cutoff.
    query = db.query(PayrollPeriod).filter(
        PayrollPeriod.factory_code == factory_code,
        PayrollPeriod.start_date <= as_utc(end_date),
        PayrollPeriod.end_date >= as_utc(start_date),
    )
    if exclude_id is not None:
        query = query.filter(PayrollPeriod.id != exclude_id)
    conflict = query.order_by(PayrollPeriod.id).first()
    if conflict:
        raise HTTPException(
            409,
            f"Payroll period dates overlap {conflict.period_no} ({conflict.status}); "
            "choose non-overlapping dates",
        )


def create_period(payload: PayrollPeriodIn, db: Session, current: User) -> PayrollPeriod:
    if payload.status not in PERIOD_CREATE_STATUSES:
        raise HTTPException(400, "New payroll periods must be draft or open")
    _validate_period_dates(payload.start_date, payload.end_date)
    factory_code = selected_factory_code(current)
    _lock_period_schedule(db, factory_code)
    period_no = payload.period_no.strip() if payload.period_no else _period_no_for(db, payload.start_date, factory_code)
    if db.query(PayrollPeriod.id).filter(
        PayrollPeriod.factory_code == factory_code,
        PayrollPeriod.period_no == period_no,
    ).first():
        raise HTTPException(400, "Payroll period number already exists")
    if len(payload.name) > 128:
        raise HTTPException(422, "Payroll period name exceeds the 128-character storage limit")
    _assert_period_dates_available(db, factory_code, payload.start_date, payload.end_date)
    period = add_payroll_period(db, factory_code=factory_code, period_no=period_no,
        name=payload.name, start_date=as_utc(payload.start_date),
        end_date=as_utc(payload.end_date), status=payload.status,
        created_by=current.id, notes=payload.notes)
    log_action(db, current, "create", "PayrollPeriod", period.id, new_value={"period_no": period.period_no})
    db.commit()
    db.refresh(period)
    return period


def list_periods(db: Session, current: User, status: str | None=None):
    qry = db.query(PayrollPeriod).filter(PayrollPeriod.factory_code == selected_factory_code(current))
    if status:
        qry = qry.filter(PayrollPeriod.status == status)
    return qry.order_by(PayrollPeriod.start_date.desc(), PayrollPeriod.id.desc()).all()


PERIOD_STATUSES = {"draft", "open", "locked", "approved", "paid", "cancelled"}
PERIOD_MANAGE_STATUS_TRANSITIONS = {
    "draft": {"draft", "open", "cancelled"},
    "open": {"draft", "open", "cancelled"},
    "locked": {"open", "locked", "cancelled"},
    "approved": {"approved"},
    "paid": {"paid"},
    "cancelled": {"cancelled"},
}


def update_period(period_id: int, payload: PayrollPeriodUpdate, db: Session, current: User):
    factory_code = selected_factory_code(current)
    _lock_period_schedule(db, factory_code)
    period = db.query(PayrollPeriod).filter(PayrollPeriod.id == period_id, PayrollPeriod.factory_code == factory_code).populate_existing().with_for_update().first()
    if not period:
        raise HTTPException(404, 'Payroll period not found')
    changes = payload.model_dump(exclude_unset=True)
    if 'status' in changes:
        next_status = changes['status']
        if next_status not in PERIOD_STATUSES:
            raise HTTPException(400, 'Invalid payroll period status')
        if next_status not in PERIOD_MANAGE_STATUS_TRANSITIONS.get(period.status, {period.status}):
            raise HTTPException(409, 'Use the dedicated lock, approval, or payment action for this payroll status')
    start_date = changes.get('start_date', period.start_date)
    end_date = changes.get('end_date', period.end_date)
    _validate_period_dates(start_date, end_date)
    if changes.get('period_no'):
        exists = db.query(PayrollPeriod.id).filter(PayrollPeriod.factory_code == factory_code, PayrollPeriod.period_no == changes['period_no'], PayrollPeriod.id != period.id).first()
        if exists:
            raise HTTPException(400, 'Payroll period number already exists')
    if 'name' in changes and changes['name'] is not None and (len(changes['name']) > 128):
        raise HTTPException(422, 'Payroll period name exceeds the 128-character storage limit')
    # Shrinking legacy overlap remains available for repair.
    if as_utc(start_date) < as_utc(period.start_date) or as_utc(end_date) > as_utc(period.end_date):
        _assert_period_dates_available(db, factory_code, start_date, end_date, exclude_id=period.id)
    for key in ('start_date', 'end_date'):
        if key in changes:
            changes[key] = as_utc(changes[key])
    old = {key: getattr(period, key) for key in changes.keys() if hasattr(period, key)}
    apply_payroll_period_changes(period, changes)
    log_action(db, current, 'update', 'PayrollPeriod', period.id, old_value=old, new_value=changes)
    db.commit()
    db.refresh(period)
    return period


def lock_period(period_id: int, db: Session, current: User):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(PayrollPeriod.id == period_id, PayrollPeriod.factory_code == factory_code).populate_existing().with_for_update().first()
    if not period:
        raise HTTPException(404, 'Payroll period not found')
    if period.status in {'approved', 'paid', 'cancelled'}:
        raise HTTPException(409, f'Cannot lock a {period.status} payroll period')
    old_status = period.status
    apply_payroll_period_changes(period, {'status': 'locked'})
    log_action(db, current, 'lock', 'PayrollPeriod', period.id, old_value={'status': old_status}, new_value={'status': period.status})
    db.commit()
    db.refresh(period)
    return period


def approve_period(period_id: int, db: Session, current: User):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(PayrollPeriod.id == period_id, PayrollPeriod.factory_code == factory_code).populate_existing().with_for_update().first()
    if not period:
        raise HTTPException(404, 'Payroll period not found')
    if period.status != 'locked':
        raise HTTPException(409, 'Only locked payroll periods can be approved')
    old_status = period.status
    apply_payroll_period_changes(period, {'status': 'approved', 'approved_by': current.id, 'approved_at': utcnow()})
    update_period_record_status(db, factory_code, period.id, ['recorded'], 'approved')
    log_action(db, current, 'approve', 'PayrollPeriod', period.id, old_value={'status': old_status}, new_value={'status': period.status})
    db.commit()
    db.refresh(period)
    return period


def mark_period_paid(period_id: int, db: Session, current: User):
    factory_code = selected_factory_code(current)
    period = db.query(PayrollPeriod).filter(PayrollPeriod.id == period_id, PayrollPeriod.factory_code == factory_code).populate_existing().with_for_update().first()
    if not period:
        raise HTTPException(404, 'Payroll period not found')
    if period.status != 'approved':
        raise HTTPException(409, 'Only approved payroll periods can be marked paid')
    apply_payroll_period_changes(period, {'status': 'paid'})
    update_period_record_status(db, factory_code, period.id, ['recorded', 'approved'], 'paid')
    log_action(db, current, 'mark_paid', 'PayrollPeriod', period.id, new_value={'status': period.status})
    db.commit()
    db.refresh(period)
    return period

RECORD_STATUSES = {"recorded", "voided", "approved", "paid"}


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


def _dget(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if _present(value):
            return value
    return None


def _load_employee_maps(
    db: Session,
    employee_ids: set[int],
    *,
    include_search_fields: bool = False,
) -> tuple[dict[int, Employee], dict[int, Department]]:
    employee_fields = [Employee.id, Employee.full_name, Employee.department_id]
    department_fields = [Department.id, Department.name]
    if include_search_fields:
        employee_fields.append(Employee.employee_no)
        department_fields.append(Department.code)
    employees = {
        int(e.id): e
        for e in (
            db.query(Employee)
            .options(load_only(*employee_fields))
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
            .options(load_only(*department_fields))
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


def _filtered_record_query(
    db: Session,
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


def list_records(db: Session, current: User, period_id: int | None=None, employee_id: int | None=None, department_id: int | None=None, date_from: datetime | None=None, date_to: datetime | None=None, status: str | None=None, limit: int=200, page: int | None=None, page_size: int | None=None):
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


def _payroll_order_reference_variants(db, reference: str) -> set[str]:
    # Historical factory SO display aliases now identify actual PO references.
    # Either payroll field may hold that old displayed value; don't infer type
    # merely from which denormalized snapshot column contains it.
    return order_reference_variants(db, "SO", reference) | order_reference_variants(db, "PO", reference) | {reference}


def _payroll_order_reference_match(db, column, namespace: str, pattern: str):
    variants = _payroll_order_reference_variants(db, pattern.strip("%"))
    return or_(order_reference_contains(column, pattern), column.in_(variants))


def order_qr_status_orders(db: Session, current: User, search: str | None=None, limit: int=50):
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
            _payroll_order_reference_match(db, PayrollQrLabel.sales_order_no, "SO", pattern),
            _payroll_order_reference_match(db, PayrollQrLabel.production_no, "PO", pattern),
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

PAYROLL_QR_TOKEN_LENGTH = 9

PAYROLL_WORK_TOKEN_PREFIX = "2"

PAYROLL_QR_TOKEN_ID_WIDTH = PAYROLL_QR_TOKEN_LENGTH - 1


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


def _numeric_qr_token(prefix: str, record_id: int) -> str:
    if record_id <= 0 or record_id >= 10**PAYROLL_QR_TOKEN_ID_WIDTH:
        raise HTTPException(500, "Payroll QR identifier is outside the supported range")
    return f"{prefix}{record_id:0{PAYROLL_QR_TOKEN_ID_WIDTH}d}"


def _work_qr_token(label_id: int) -> str:
    return _numeric_qr_token(PAYROLL_WORK_TOKEN_PREFIX, label_id)


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
        "closure_details": label.closure_details,
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
    db: Session,
    labels: list[PayrollQrLabel],
) -> tuple[dict[int, PayrollRecord], dict[int, Employee], dict[int, Department]]:
    record_ids = {int(label.payroll_record_id) for label in labels if label.payroll_record_id}
    records = {
        int(record.id): record
        for record in (db.query(PayrollRecord).filter(PayrollRecord.id.in_(record_ids)).all() if record_ids else [])
    }
    employees, departments = _load_employee_maps(db, {int(record.employee_id) for record in records.values()})
    return records, employees, departments


def _order_qr_label_query(db: Session, order_no: str, factory_code: str):
    variants = _payroll_order_reference_variants(db, order_no)
    return db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == factory_code,
        PayrollQrLabel.status.notin_(["superseded", "closed"]),
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


def order_qr_status_report(db: Session, current: User, order_no: str='', status: str | None=None, limit: int=100, offset: int=0):
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


def _sewing_report_factory_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized not in {"MIL", "BST", "ECO"}:
        raise HTTPException(400, "Factory must be MIL, BST, or ECO")
    return normalized


def _sewing_report_options(db: Session, factory_code: str) -> dict[str, list[dict[str, str]]]:
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
    # HR teams can be report filters without creating operational Sewing flows.
    report_managers = db.query(Employee).filter(
        Employee.factory_code == factory_code,
    ).all()
    manager_ids = {row.manager_employee_id for row in report_managers if row.manager_employee_id}
    salary_masters = [
        {"value": f"manager:{manager.id}", "label": manager.full_name}
        for manager in report_managers
        if manager.id in manager_ids or (manager.hr_profile_json or {}).get("payroll_report_group") is True
    ]
    report_groups = [
        {"value": f"manager:{manager.id}", "label": f"{manager.full_name} | {factory_code}"}
        for manager in report_managers
        if manager.status == "active" and (manager.hr_profile_json or {}).get("payroll_report_group") is True
    ]

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
        "salary_masters": salary_masters,
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
        ] + report_groups),
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


def sewing_production_report_options(db: Session, current: User, factory_code: str | None=None):
    scoped_factory = selected_factory_code(current)
    if factory_code:
        require_factory_access(current, factory_code)
    return _sewing_report_options(db, scoped_factory)


def _sewing_report_base_query(db: Session, factory_code: str):
    return (
        db.query(PayrollRecord, Employee, PayrollQrLabel, Model, SewingFlow)
        .join(Employee, Employee.id == PayrollRecord.employee_id)
        .outerjoin(PayrollQrLabel, PayrollQrLabel.payroll_record_id == PayrollRecord.id)
        .outerjoin(Model, Model.id == PayrollRecord.model_id)
        .outerjoin(SewingFlow, SewingFlow.id == PayrollQrLabel.sewing_flow_id)
        .filter(PayrollRecord.factory_code == factory_code)
    )


def _filtered_sewing_production_report_query(
    db: Session,
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
    report_view: str = "details",
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
    if report_view == "salary" and (sewing_flow_id or (sewing_line and not sewing_line.strip().startswith("manager:"))):
        raise HTTPException(422, "Select an employee Master for the salary report")
    if sewing_flow_id:
        qry = qry.filter(PayrollQrLabel.sewing_flow_id == sewing_flow_id)
    if sewing_line and sewing_line.strip().startswith("manager:"):
        try:
            manager_id = int(sewing_line.strip().removeprefix("manager:"))
        except ValueError:
            raise HTTPException(400, "Invalid report group") from None
        manager = db.query(Employee).filter(Employee.id == manager_id, Employee.factory_code == factory_code).first()
        if not manager or (report_view != "salary" and (manager.hr_profile_json or {}).get("payroll_report_group") is not True):
            raise HTTPException(404, "Report group not found")
        leader = Employee.id == manager_id
        if report_view == "salary":
            leader = and_(leader, Employee.manager_employee_id.is_(None))
        qry = qry.filter(Employee.factory_code == factory_code, or_(
            Employee.manager_employee_id == manager_id, leader,
        ))
    elif sewing_line and sewing_line.strip():
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
    people = {row.id: row for row in qry.session.query(
        Employee.id, Employee.full_name, Employee.manager_employee_id, Employee.factory_code, Employee.hr_profile_json,
    ).filter(
        Employee.id.in_([key[0] for key in employees]),
    )} if employees else {}
    manager_ids = {row.manager_employee_id for row in people.values() if row.manager_employee_id}
    managers = {row.id: row for row in qry.session.query(
        Employee.id, Employee.full_name, Employee.factory_code,
    ).filter(Employee.id.in_(manager_ids))} if manager_ids else {}
    team_leaders = {row[0] for row in qry.session.query(Employee.manager_employee_id).filter(
        Employee.manager_employee_id.in_(people),
    ).distinct()} if people else set()
    for item in employees.values():
        person = people[item["employee_id"]]
        manager = managers.get(person.manager_employee_id)
        if manager and manager.factory_code == person.factory_code:
            item["master_id"], item["master_name"] = manager.id, manager.full_name
        elif not person.manager_employee_id and (person.id in team_leaders or (person.hr_profile_json or {}).get("payroll_report_group") is True):
            item["master_id"], item["master_name"] = person.id, person.full_name
    return sorted(employees.values(), key=lambda row: (row.get("master_name", "").casefold(), row.get("master_id", 0), row["employee_name"].casefold(), row["employee_id"], row["currency"]))


def _sewing_report_product_quantity(qry, *, size: str | None = None) -> Decimal:
    """Count produced batches once, never once per paid operation/employee.

    Linked batches use saved Sewing output. Legacy/manual work without Sewing
    records uses the largest operation subtotal per batch/model/size; split
    labels and work shared by employees are summed before deduplication.
    """
    order = func.coalesce(cast(PayrollRecord.production_order_id, String), PayrollRecord.production_no, PayrollRecord.sales_order_no, "")
    batch = func.coalesce(cast(PayrollRecord.production_batch_id, String), PayrollQrLabel.cutting_passport_no, PayrollRecord.batch_no, "")
    model = func.coalesce(PayrollRecord.model_code, "")
    size_key = func.coalesce(PayrollQrLabel.size, PayrollRecord.raw_work_json["size"].as_string(), "")
    operation = func.coalesce(PayrollRecord.operation_code, PayrollRecord.operation_name, "")
    operation_totals = qry.with_entities(
        PayrollRecord.production_order_id.label("po_id"), PayrollRecord.production_batch_id.label("batch_id"),
        order.label("order_ref"), batch.label("batch_ref"), model.label("model_ref"),
        size_key.label("size_ref"), operation.label("operation_ref"), func.sum(PayrollRecord.quantity).label("quantity"),
    ).group_by(PayrollRecord.production_order_id, PayrollRecord.production_batch_id,
               order, batch, model, size_key, operation).subquery()
    # Collapse operations in SQL: a report can contain tens of thousands of paid
    # operations but only hundreds of physical batches. Avoid materializing every
    # operation in Python just to retain the largest subtotal for each batch.
    physical_keys = [operation_totals.c[name] for name in
                     ("po_id", "batch_id", "order_ref", "batch_ref", "model_ref", "size_ref")]
    rows = qry.session.query(*physical_keys, func.max(operation_totals.c.quantity)).group_by(*physical_keys).all()
    fallback = {}
    linked = set()
    for po_id, batch_id, order_ref, batch_ref, model_ref, label_size, quantity in rows:
        key = (po_id, batch_id, order_ref, batch_ref, model_ref, label_size)
        fallback[key] = max(fallback.get(key, Decimal(0)), quantity or Decimal(0))
        if po_id is not None:
            linked.add((po_id, batch_id))
    actual = {}
    if linked and not size:
        record_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
        for po_id, batch_id, quantity in qry.session.query(
            WorkOrder.production_order_id, record_batch, func.sum(SewingRecord.passed_qty),
        ).join(SewingRecord, SewingRecord.work_order_id == WorkOrder.id).filter(
            WorkOrder.production_order_id.in_({key[0] for key in linked}),
            WorkOrder.operation == "sewing", WorkOrder.status != "cancelled",
        ).group_by(WorkOrder.production_order_id, record_batch).all():
            if (po_id, batch_id) in linked:
                actual[(po_id, batch_id)] = Decimal(quantity or 0)
    return sum(actual.values(), Decimal(0)) + sum(
        (quantity for key, quantity in fallback.items() if key[:2] not in actual), Decimal(0),
    )


def sewing_production_report(db: Session, current: User, date_from: datetime | None=None, date_to: datetime | None=None, employee_id: int | None=None, order_no: str | None=None, cutting_reference: str | None=None, model_code: str | None=None, sewing_flow_id: int | None=None, sewing_line: str | None=None, operation: str | None=None, barcode: str | None=None, size: str | None=None, factory_code: str | None=None, status: str='active', report_view: Literal['details', 'salary']='details', limit: int=100, offset: int=0):
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
        report_view=report_view,
    )

    aggregate = qry.with_entities(
        func.coalesce(func.sum(PayrollRecord.quantity), 0),
        func.coalesce(func.sum(PayrollRecord.total_amount), 0),
        func.count(),
        func.min(func.nullif(PayrollRecord.currency, "")),
        func.max(func.nullif(PayrollRecord.currency, "")),
    ).one()
    total = int(aggregate[2])
    first_currency, last_currency = aggregate[3], aggregate[4]
    report_currency = (first_currency if first_currency == last_currency else "MIXED") or "UZS"
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
        "total_product_quantity": _sewing_report_product_quantity(qry, size=size),
        "total_amount": aggregate[1],
        "currency": report_currency,
        "options": _sewing_report_options(db, factory_code),
    }


def sewing_production_report_excel(db: Session, current: User, lang: ReportLanguage='uz', date_from: datetime | None=None, date_to: datetime | None=None, employee_id: int | None=None, order_no: str | None=None, cutting_reference: str | None=None, model_code: str | None=None, sewing_flow_id: int | None=None, sewing_line: str | None=None, operation: str | None=None, barcode: str | None=None, size: str | None=None, factory_code: str | None=None, status: str='active', report_view: Literal['details', 'salary']='details'):
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
        report_view=report_view,
    )
    if report_view == "salary":
        items = _sewing_salary_summary(qry)
    else:
        rows = qry.order_by(PayrollRecord.scanned_at.desc(), PayrollRecord.id.desc()).all()
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
    return workbook, filename


def export_process_qr_operations(payload: ProcessQrExportIn, current: User):
    require_factory_access(current, payload.factory)
    return build_process_qr_xlsx(payload)

PAYROLL_EMPLOYEE_TOKEN_PREFIX = "1"


def _employee_qr_token(employee_id: int) -> str:
    return _numeric_qr_token(PAYROLL_EMPLOYEE_TOKEN_PREFIX, employee_id)


def _employee_scan_payload(
    employee: Employee, *, badge_id: str, source: str, db: Session,
    departments: dict[int, Department] | None = None,
) -> dict[str, Any]:
    if employee.status == "archived":
        raise HTTPException(404, "Employee not found")
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


def search_payroll_employees(db: Session, q: str, current: User):
    terms = q.strip().split()
    if len(q.strip()) < 2:
        return {"items": [], "has_more": False}
    query = db.query(Employee, Department).outerjoin(Department, Employee.department_id == Department.id).filter(
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


def resolve_employee_number(employee_no: str, db: Session, current: User):
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
    if normalized.isascii() and normalized.isdigit() and 0 < int(normalized) <= 2147483647:
        fallback = db.query(Employee).filter(
            Employee.id == int(normalized),
            Employee.factory_code == selected_factory_code(current),
            or_(Employee.employee_no.is_(None), func.trim(Employee.employee_no) == ""),
        ).first()
        if employee and fallback and employee.id != fallback.id:
            raise HTTPException(409, "Employee number is ambiguous; select the employee by name or scan their badge QR")
        employee = employee or fallback
    if not employee and normalized.upper().startswith("EMP-") and normalized[4:].isdigit():
        employee = db.query(Employee).filter(
            Employee.id == int(normalized[4:]),
            Employee.factory_code == selected_factory_code(current),
        ).first()
    if not employee:
        employee = merged_employee(db, selected_factory_code(current), employee_no=normalized)
    if not employee and normalized.upper().startswith("EMP-") and normalized[4:].isdigit():
        employee = merged_employee(db, selected_factory_code(current), employee_id=int(normalized[4:]))
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


def resolve_qr_token(token: str, db: Session, current: User):
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
            employee = merged_employee(db, factory_code, employee_id=record_id)
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


def _work_label_id_from_token(token: str) -> int | None:
    normalized = token.strip()
    if len(normalized) != PAYROLL_QR_TOKEN_LENGTH or not normalized.isdigit():
        return None
    if not normalized.startswith(PAYROLL_WORK_TOKEN_PREFIX):
        return None
    return int(normalized[1:])


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


def list_qr_labels(db: Session, current: User, search: str | None=None, status: str | None=None, order_no: str | None=None, production_order_id: int | None=None, include_superseded: bool=False, limit: int=100, offset: int=0):
    if status and status not in {"available", "scanned", "superseded", "closed"}:
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
    closed_count = qry.filter(PayrollQrLabel.status == "closed").count()
    if status:
        qry = qry.filter(PayrollQrLabel.status == status)
    elif not include_superseded:
        qry = qry.filter(PayrollQrLabel.status.notin_(["superseded", "closed"]))
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
        "closed_count": closed_count,
    }


def _adjustment_signed_amount(adjustment: PayrollAdjustment) -> Decimal:
    amount = adjustment.amount or Decimal("0")
    return -amount if adjustment.adjustment_type == "deduction" else amount


def _filtered_adjustment_query(
    db: Session,
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


def payroll_summary(db: Session, current: User, period_id: int | None=None, employee_id: int | None=None, department_id: int | None=None, date_from: datetime | None=None, date_to: datetime | None=None, group_by_operation: bool=True, page: int | None=None, page_size: int | None=None, employee_search: str | None=None):
    paged = page is not None or page_size is not None or bool((employee_search or "").strip())
    effective_page = page or 1
    effective_page_size = page_size or 50
    normalized_search = " ".join((employee_search or "").split()).casefold()
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

        if group_by_operation and not paged:
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

    employees, departments = _load_employee_maps(
        db, employee_ids, include_search_fields=bool(normalized_search)
    )
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

    if group_by_operation and not paged:
        for key, op in operation_groups.items():
            employee_key = (key[0], key[1])
            employee_groups[employee_key]["operations"].append(PayrollSummaryOperationOut(**op))

    employees_out = [PayrollSummaryEmployeeOut(**row) for row in employee_groups.values()]
    employees_out.sort(key=lambda row: (str(row.employee_name).lower(), row.employee_id))
    if normalized_search:
        search_terms = normalized_search.split()

        def matches_employee(row: PayrollSummaryEmployeeOut) -> bool:
            employee = employees.get(row.employee_id)
            department = (
                departments.get(int(employee.department_id))
                if employee and employee.department_id
                else None
            )
            searchable = [
                row.employee_name,
                getattr(employee, "employee_no", None),
                getattr(department, "code", None),
                row.department_name,
            ]
            normalized_fields = [str(value).casefold() for value in searchable if value]
            if normalized_search.isdecimal() and normalized_search == str(row.employee_id):
                return True
            return all(
                any(term in field for field in normalized_fields)
                for term in search_terms
            )

        employees_out = [row for row in employees_out if matches_employee(row)]

    employees_total = len(employees_out)
    if paged:
        start = (effective_page - 1) * effective_page_size
        employees_out = employees_out[start : start + effective_page_size]

    if group_by_operation and paged and employees_out:
        selected_groups = {(row.employee_id, row.currency) for row in employees_out}
        page_operation_query = _filtered_record_query(
            db,
            factory_code=factory_code,
            period_id=period_id,
            employee_id=employee_id,
            department_id=department_id,
            date_from=date_from,
            date_to=date_to,
        ).filter(
            PayrollRecord.status != "voided",
            or_(
                *(
                    and_(
                        PayrollRecord.employee_id == selected_employee_id,
                        func.coalesce(PayrollRecord.currency, "UZS") == selected_currency,
                    )
                    for selected_employee_id, selected_currency in selected_groups
                )
            ),
        ).options(load_only(
            PayrollRecord.employee_id,
            PayrollRecord.currency,
            PayrollRecord.quantity,
            PayrollRecord.total_amount,
            PayrollRecord.operation_section,
            PayrollRecord.operation_code,
            PayrollRecord.operation_name,
        ))
        page_operation_groups: dict[
            tuple[int, str, str | None, str | None, str | None], dict[str, Any]
        ] = {}
        for record in page_operation_query.yield_per(400):
            key = (
                int(record.employee_id),
                str(record.currency or "UZS"),
                record.operation_section,
                record.operation_code,
                record.operation_name,
            )
            op = page_operation_groups.setdefault(
                key,
                {
                    "employee_id": key[0],
                    "operation_section": key[2],
                    "operation_code": key[3],
                    "operation_name": key[4],
                    "currency": key[1],
                    "records_count": 0,
                    "quantity": Decimal("0"),
                    "total_amount": Decimal("0"),
                },
            )
            op["records_count"] += 1
            op["quantity"] += record.quantity or Decimal("0")
            op["total_amount"] += record.total_amount or Decimal("0")
        page_employees = {(row.employee_id, row.currency): row for row in employees_out}
        for key, op in page_operation_groups.items():
            page_employees[(key[0], key[1])].operations.append(
                PayrollSummaryOperationOut(**op)
            )
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
        employees_total=employees_total if paged else None,
        employee_page=effective_page if paged else None,
        employee_page_size=effective_page_size if paged else None,
        employees_has_more=(
            effective_page * effective_page_size < employees_total if paged else None
        ),
        employee_search=normalized_search or None if paged else None,
    )


def list_adjustments(db: Session, current: User, period_id: int | None=None, employee_id: int | None=None, department_id: int | None=None, date_from: datetime | None=None, date_to: datetime | None=None, page: int | None=None, page_size: int | None=None):
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
    employee_ids = {int(row.employee_id) for row in rows}
    employee_labels = {}
    if employee_ids:
        labels = db.query(
            Employee.id,
            Employee.full_name,
            Employee.department_id,
            Department.name.label("department_name"),
        ).outerjoin(Department, Employee.department_id == Department.id).filter(
            Employee.factory_code == selected_factory_code(current),
            Employee.id.in_(employee_ids),
        ).all()
        employee_labels = {
            int(row.id): {
                "employee_name": row.full_name,
                "department_id": row.department_id,
                "department_name": row.department_name,
            }
            for row in labels
        }
    serialized_rows = [
        {
            **PayrollAdjustmentOut.model_validate(row).model_dump(),
            **employee_labels.get(int(row.employee_id), {}),
        }
        for row in rows
    ]
    return {
        "rows": serialized_rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


def list_payroll_employee_options(db: Session, current: User, search: str='', page: int=1, page_size: int=50, selected_id: int | None=None):
    factory_code = selected_factory_code(current)
    normalized_search = search.strip()
    terms = normalized_search.split()
    query = db.query(
        Employee.id,
        Employee.full_name,
        Employee.employee_no,
        Employee.position,
        Employee.department_id,
        Department.code.label("department_code"),
        Department.name.label("department_name"),
    ).outerjoin(Department, Employee.department_id == Department.id).filter(
        Employee.factory_code == factory_code,
    )
    for term in terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(
            Employee.full_name.ilike(pattern, escape="\\"),
            Employee.employee_no.ilike(pattern, escape="\\"),
            Employee.position.ilike(pattern, escape="\\"),
            Department.code.ilike(pattern, escape="\\"),
            Department.name.ilike(pattern, escape="\\"),
            cast(Employee.id, String).ilike(pattern, escape="\\"),
        ))
    rows = query.order_by(func.lower(Employee.full_name), Employee.employee_no, Employee.id).offset(
        (page - 1) * page_size,
    ).limit(page_size + 1).all()

    def serialize(row):
        return {
            "id": int(row.id),
            "full_name": row.full_name,
            "employee_no": row.employee_no,
            "position": row.position,
            "department_id": row.department_id,
            "department_code": row.department_code,
            "department_name": row.department_name,
        }

    selected = None
    if selected_id:
        selected_row = db.query(
            Employee.id,
            Employee.full_name,
            Employee.employee_no,
            Employee.position,
            Employee.department_id,
            Department.code.label("department_code"),
            Department.name.label("department_name"),
        ).outerjoin(Department, Employee.department_id == Department.id).filter(
            Employee.factory_code == factory_code,
            Employee.id == selected_id,
        ).first()
        selected = serialize(selected_row) if selected_row else None
    return {
        "items": [serialize(row) for row in rows[:page_size]],
        "selected": selected,
        "page": page,
        "page_size": page_size,
        "search": normalized_search,
        "has_more": len(rows) > page_size,
    }


def print_split_record_labels(record_id: int, db: Session, current: User):
    from app.models.payroll_labels_service import split_label_card, split_labels_html

    factory = selected_factory_code(current)
    original = db.query(PayrollQrLabel).filter_by(payroll_record_id=record_id, factory_code=factory).first()
    if not original:
        raise HTTPException(404, "Issued payroll QR record not found")
    labels = db.query(PayrollQrLabel).filter_by(split_from_label_id=original.id, factory_code=factory).order_by(PayrollQrLabel.id).all()
    if not labels or any(label.status == "superseded" for label in labels):
        raise HTTPException(409, "Split labels changed; reload the current allocations")
    cards = []
    for label in labels:
        record = db.get(PayrollRecord, label.payroll_record_id) if label.payroll_record_id else None
        employee = db.get(Employee, record.employee_id) if record else None
        if not record or record.status != "recorded" or not employee or employee.factory_code != factory:
            raise HTTPException(409, "Split allocations are no longer recorded")
        token = _work_qr_token(label.id)
        cards.append(split_label_card(label, employee, token))
    return split_labels_html(cards)


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


MUTATION_LOCKED_PERIOD_STATUSES = {"locked", "approved", "paid", "cancelled"}
