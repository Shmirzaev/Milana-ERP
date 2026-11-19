"""Adjustment and reversal rules coordinate one supplied-Session transaction."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.dt import utcnow
from app.libs.dto.people.payroll import PayrollAdjustmentIn, PayrollRecordReversalIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.people.payroll_service import MUTATION_LOCKED_PERIOD_STATUSES, _adjustment_signed_amount, _present
from app.schemas import Employee, PayrollAdjustment, PayrollPeriod, PayrollRecord, User
from app.schemas.people.payroll_adjustment_persistence import add_payroll_adjustment, delete_payroll_adjustment


ADJUSTMENT_TYPES = {"bonus", "deduction"}

PAYROLL_ADJUSTMENT_MAX_AMOUNT = Decimal("999999999999.99")


def _to_money_decimal(value: Any) -> Decimal:
    if not _present(value):
        raise HTTPException(400, "amount is required")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise HTTPException(400, f"Invalid numeric value: {value}")
        cents = amount.quantize(Decimal("0.01"))
        if amount != cents:
            raise HTTPException(400, "Adjustment amount supports at most 2 decimal places")
        return cents
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


def _assert_period_accepts_adjustments(period: PayrollPeriod | None) -> None:
    if not period:
        return
    if period.status in MUTATION_LOCKED_PERIOD_STATUSES:
        raise HTTPException(409, f"Payroll period {period.period_no} is {period.status}")


def create_adjustment(
    payload: PayrollAdjustmentIn,
    db: Session,
    current: User,
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
    adjustment = add_payroll_adjustment(db,
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


def delete_adjustment(
    adjustment_id: int,
    db: Session,
    current: User,
):
    factory_code = selected_factory_code(current)
    adjustment = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.id == adjustment_id,
        PayrollAdjustment.factory_code == factory_code,
    ).first()
    if not adjustment:
        raise HTTPException(404, "Payroll adjustment not found")
    discovered_period_id = adjustment.payroll_period_id
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
    adjustment = db.query(PayrollAdjustment).filter(
        PayrollAdjustment.id == adjustment_id,
        PayrollAdjustment.factory_code == factory_code,
    ).populate_existing().with_for_update().first()
    if not adjustment:
        raise HTTPException(404, "Payroll adjustment not found")
    if adjustment.payroll_period_id != discovered_period_id:
        raise HTTPException(409, "Payroll adjustment assignment changed; retry the deletion")
    if adjustment.source_payroll_record_id:
        raise HTTPException(409, "Linked payroll reversal adjustments cannot be deleted")
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
    delete_payroll_adjustment(db, adjustment)
    db.commit()
    return None


def reverse_record_as_adjustment(
    record_id: int,
    payload: PayrollRecordReversalIn,
    db: Session,
    current: User,
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
    adjustment = add_payroll_adjustment(db,
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
