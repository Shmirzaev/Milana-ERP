"""Schema-owned persistence for manual payroll adjustment creation."""

from sqlalchemy.orm import Session

from app.libs.types.people import PayrollAdjustmentCreateCommand
from app.schemas.people.payroll import PayrollAdjustment


def insert_manual_payroll_adjustment(
    db: Session,
    command: PayrollAdjustmentCreateCommand,
) -> PayrollAdjustment:
    """Stage and flush the validated manual adjustment in the supplied transaction."""
    adjustment = PayrollAdjustment(
        factory_code=command.factory_code,
        payroll_period_id=command.payroll_period_id,
        employee_id=command.employee_id,
        adjustment_type=command.adjustment_type,
        amount=command.amount,
        currency=command.currency,
        reason=command.reason,
        created_by=command.created_by,
        created_at=command.created_at,
    )
    db.add(adjustment)
    db.flush()
    return adjustment
