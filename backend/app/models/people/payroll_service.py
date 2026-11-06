"""Payroll operations with explicit actor, Session, business checks and transaction ownership."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import load_only, object_session
from app.core.dt import as_utc, utcnow
from app.core.order_reference import (
    canonical_order_reference, order_reference_variants,
)
from app.schemas import (
    Department,
    Employee,
    PayrollPeriod,
    PayrollQrLabel,
    PayrollRecord,
    User,
)
from app.libs.dto.people.payroll import (
    PayrollPeriodIn,
    PayrollPeriodUpdate,
)
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from datetime import datetime
import json
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import load_only, object_session
from app.core.dt import as_utc, utcnow
from app.core.order_reference import (
    canonical_order_reference, order_reference_contains, order_reference_variants,
)
from app.schemas import (
    Department,
    Employee,
    PayrollPeriod,
    PayrollQrLabel,
    PayrollRecord,
    User,
)
from app.libs.dto.people.payroll import (
    PayrollPeriodIn,
    PayrollPeriodUpdate,
)
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from datetime import datetime
import json
from typing import Any
from fastapi import HTTPException
from sqlalchemy.orm import load_only, object_session
from app.core.dt import as_utc, utcnow
from app.core.order_reference import (
    canonical_order_reference, order_reference_variants,
)
from app.schemas import (
    Department,
    Employee,
    PayrollPeriod,
    PayrollRecord,
    User,
)
from app.libs.dto.people.payroll import (
    PayrollPeriodIn,
    PayrollPeriodUpdate,
)
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
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


def list_periods(db: Session, current: User=None, status: str | None=None):
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


def update_period(period_id: int, payload: PayrollPeriodUpdate, db: Session, current: User=None):
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


def lock_period(period_id: int, db: Session, current: User=None):
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


def approve_period(period_id: int, db: Session, current: User=None):
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


def mark_period_paid(period_id: int, db: Session, current: User=None):
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


def list_records(db: Session, current: User=None, period_id: int | None=None, employee_id: int | None=None, department_id: int | None=None, date_from: datetime | None=None, date_to: datetime | None=None, status: str | None=None, limit: int=200, page: int | None=None, page_size: int | None=None):
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


def order_qr_status_orders(db: Session, current: User=None, search: str | None=None, limit: int=50):
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


def order_qr_status_report(db: Session, current: User=None, order_no: str='', status: str | None=None, limit: int=100, offset: int=0):
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
