
"""Payroll period creation owns validation, schedule locking, audit and commit."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.dt import as_utc
from app.libs.dto.people.payroll import PayrollPeriodIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_period_lock_service import lock_period_schedule as _lock_period_schedule
from app.schemas import PayrollPeriod, User
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
