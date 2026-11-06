"""Payroll adjustment rows; business rules and commit remain with the caller."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas import PayrollAdjustment


def add_payroll_adjustment(
    db: Session, *, factory_code: str, payroll_period_id: int | None,
    employee_id: int, adjustment_type: str, amount: Decimal, currency: str,
    reason: str, created_by: int, created_at: datetime,
    source_payroll_record_id: int | None = None,
) -> PayrollAdjustment:
    adjustment = PayrollAdjustment(
        factory_code=factory_code,
        payroll_period_id=payroll_period_id,
        source_payroll_record_id=source_payroll_record_id,
        employee_id=employee_id,
        adjustment_type=adjustment_type,
        amount=amount,
        currency=currency,
        reason=reason,
        created_by=created_by,
        created_at=created_at,
    )
    db.add(adjustment)
    db.flush()
    return adjustment


def delete_payroll_adjustment(db: Session, adjustment: PayrollAdjustment) -> None:
    db.delete(adjustment)
