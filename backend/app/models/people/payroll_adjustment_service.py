"""Business operation for manually creating one payroll adjustment."""

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.dt import utcnow
from app.libs.dto.people.payroll import PayrollAdjustmentIn
from app.libs.enums.factory import FactoryCode
from app.libs.enums.people import PayrollAdjustmentType
from app.libs.types.people import PayrollAdjustmentCreateCommand
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.schemas import Employee, PayrollAdjustment, PayrollPeriod, User
from app.schemas.people.payroll_adjustment_persistence import insert_manual_payroll_adjustment


PAYROLL_ADJUSTMENT_MAX_AMOUNT = Decimal("999999999999.99")
MANUAL_ADJUSTMENT_BLOCKED_PERIOD_STATUSES = frozenset({"locked", "approved", "paid", "cancelled"})


class PayrollAdjustmentOperationError(Exception):
    """A refusal that the HTTP adapter maps to the operation's legacy response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def assert_period_accepts_manual_adjustment(period: PayrollPeriod | None) -> None:
    """Keep the manual-create refusal and message for finalized periods."""
    if period and period.status in MANUAL_ADJUSTMENT_BLOCKED_PERIOD_STATUSES:
        raise PayrollAdjustmentOperationError(409, f"Payroll period {period.period_no} is {period.status}")


def _to_money_decimal(value: object) -> Decimal:
    if value is None or value == "":
        raise PayrollAdjustmentOperationError(400, "amount is required")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise PayrollAdjustmentOperationError(400, f"Invalid numeric value: {value}")
        cents = amount.quantize(Decimal("0.01"))
        if amount != cents:
            raise PayrollAdjustmentOperationError(400, "Adjustment amount supports at most 2 decimal places")
        return cents
    except PayrollAdjustmentOperationError:
        raise
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PayrollAdjustmentOperationError(400, f"Invalid numeric value: {value}") from exc


def _normalize_adjustment_amount(payload: PayrollAdjustmentIn) -> tuple[Decimal, PayrollAdjustmentType]:
    raw_amount = _to_money_decimal(payload.amount)
    if abs(raw_amount) > PAYROLL_ADJUSTMENT_MAX_AMOUNT:
        raise PayrollAdjustmentOperationError(
            400,
            "Adjustment amount exceeds the supported maximum of 999999999999.99",
        )
    requested_type = payload.adjustment_type
    if requested_type is None:
        adjustment_type = None
    elif isinstance(requested_type, PayrollAdjustmentType):
        adjustment_type = requested_type
    else:
        normalized_type = str(requested_type).strip().lower()
        try:
            adjustment_type = PayrollAdjustmentType(normalized_type) if normalized_type else None
        except ValueError as exc:
            raise PayrollAdjustmentOperationError(400, "adjustment_type must be bonus or deduction") from exc
    if raw_amount == 0:
        raise PayrollAdjustmentOperationError(400, "Adjustment amount must be non-zero")
    if raw_amount < 0:
        if adjustment_type is PayrollAdjustmentType.BONUS:
            raise PayrollAdjustmentOperationError(400, "Negative adjustments must use adjustment_type=deduction")
        return abs(raw_amount), PayrollAdjustmentType.DEDUCTION
    return raw_amount, adjustment_type or PayrollAdjustmentType.BONUS


def create_manual_payroll_adjustment(
    db: Session,
    payload: PayrollAdjustmentIn,
    current: User,
) -> PayrollAdjustment:
    """Create and audit one adjustment; this operation owns the single commit.

    Period and employee scope checks, the period row lock, amount normalization,
    schema flush, audit append, commit and refresh retain their previous order.
    """
    factory_code = selected_factory_code(current)
    period = (
        db.query(PayrollPeriod)
        .filter(
            PayrollPeriod.id == payload.payroll_period_id,
            PayrollPeriod.factory_code == factory_code,
        )
        .populate_existing()
        .with_for_update()
        .first()
        if payload.payroll_period_id
        else None
    )
    if payload.payroll_period_id and not period:
        raise PayrollAdjustmentOperationError(404, "Payroll period not found")
    assert_period_accepts_manual_adjustment(period)
    if not db.query(Employee.id).filter(
        Employee.id == payload.employee_id,
        Employee.factory_code == factory_code,
    ).first():
        raise PayrollAdjustmentOperationError(404, "Employee not found")

    amount, adjustment_type = _normalize_adjustment_amount(payload)
    command = PayrollAdjustmentCreateCommand(
        factory_code=FactoryCode(factory_code),
        payroll_period_id=payload.payroll_period_id,
        employee_id=payload.employee_id,
        adjustment_type=adjustment_type,
        amount=amount,
        currency=(payload.currency or "UZS").upper()[:8],
        reason=payload.reason,
        created_by=current.id,
        created_at=utcnow(),
    )
    adjustment = insert_manual_payroll_adjustment(db, command)
    log_action(
        db,
        current,
        "create",
        "PayrollAdjustment",
        adjustment.id,
        new_value={
            "employee_id": adjustment.employee_id,
            "adjustment_type": adjustment.adjustment_type.value,
            "amount": adjustment.amount,
            "signed_amount": adjustment.signed_amount,
            "reason": adjustment.reason,
        },
    )
    db.commit()
    db.refresh(adjustment)
    return adjustment
