"""Correct one complete, recorded split without reissuing QR or earning twice."""
import hashlib
import json
from decimal import Decimal, ROUND_DOWN

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.schemas.payroll_split_correction import SplitAllocationOut, SplitAllocationPartOut, SplitAllocationUpdate
from app.services.audit import log_action
from app.services.factory_scope import selected_factory_code
from app.services.payroll_period_lock import lock_period_schedule
from app.services.payroll_operation import is_control_operation
from app.models import Department, Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.models.payroll_split_correction import apply_split_part_correction


def _group(db: Session, label_id: int, factory: str, *, lock: bool = False):
    selected = db.query(PayrollQrLabel).filter_by(id=label_id, factory_code=factory).first()
    if not selected:
        raise HTTPException(404, "Payroll QR label not found")
    parent_id = selected.split_from_label_id
    if not parent_id:
        raise HTTPException(409, "Select a recorded split label")
    parent = db.query(PayrollQrLabel).filter_by(id=parent_id, factory_code=factory)
    children = db.query(PayrollQrLabel).filter_by(split_from_label_id=parent_id, factory_code=factory).order_by(PayrollQrLabel.id)
    if lock:
        parent = parent.populate_existing().with_for_update()
        children = children.populate_existing().with_for_update()
    parent = parent.first()
    labels = children.all()
    if not parent or parent.status != "superseded" or not parent.payroll_record_id or len(labels) < 2:
        raise HTTPException(409, "Only saved payroll split allocations can be corrected")
    ids = {parent.payroll_record_id, *(label.payroll_record_id for label in labels)}
    records_query = db.query(PayrollRecord).filter(PayrollRecord.id.in_(ids), PayrollRecord.factory_code == factory).order_by(PayrollRecord.id)
    if lock:
        records_query = records_query.populate_existing().with_for_update()
    records = {row.id: row for row in records_query.all()}
    original = records.get(parent.payroll_record_id)
    if not original or original.status != "voided":
        raise HTTPException(409, "Original split payroll history changed; reload")
    for label in labels:
        record = records.get(label.payroll_record_id)
        if (label.status != "scanned" or not record or record.status != "recorded"
                or record.source != "payroll_scan_split" or record.scan_uid != label.label_uid
                or record.quantity != label.quantity or record.rate_per_piece != label.rate_per_piece
                or record.currency != original.currency or label.currency != original.currency
                or record.scanned_at != original.scanned_at
                or record.payroll_period_id != original.payroll_period_id):
            raise HTTPException(409, "Split allocations changed, returned, split again or finalized; reload")
    if sum(label.quantity for label in labels) != parent.quantity:
        raise HTTPException(409, "Split pieces no longer equal the original QR quantity")
    return parent, labels, records, original


def _view(db: Session, parent, labels, records, original) -> SplitAllocationOut:
    employees = {row.id: row for row in db.query(Employee).filter(Employee.id.in_([records[label.payroll_record_id].employee_id for label in labels])).all()}
    parts = [SplitAllocationPartOut(
        label_id=label.id, label_uid=label.label_uid, employee_id=records[label.payroll_record_id].employee_id,
        employee_name=employees[records[label.payroll_record_id].employee_id].full_name,
        quantity=int(label.quantity), operation_name=label.operation_name or "",
        rate_per_piece=label.rate_per_piece.quantize(Decimal("0.0001")), total_amount=records[label.payroll_record_id].total_amount.quantize(Decimal("0.01")),
        currency=label.currency,
    ) for label in labels]
    fingerprint = [
        (label.id, label.updated_at, label.status, label.payroll_record_id,
         records[label.payroll_record_id].updated_at, records[label.payroll_record_id].payroll_period_id,
         part.model_dump(mode="json"))
        for label, part in zip(labels, parts)
    ]
    revision = hashlib.sha256(json.dumps(fingerprint, default=str, sort_keys=True).encode()).hexdigest()
    return SplitAllocationOut(parent_label_id=parent.id, original_record_id=original.id, revision=revision, total_quantity=int(parent.quantity), parts=parts)


def read_split_allocation(db: Session, *, actor: User, label_id: int) -> SplitAllocationOut:
    if _is_returned(db, actor, label_id):
        from app.services.payroll_returned_split_correction import read_returned_split_allocation
        return read_returned_split_allocation(db, actor=actor, label_id=label_id)
    return _view(db, *_group(db, label_id, selected_factory_code(actor)))


def correct_split_allocation(db: Session, *, actor: User, label_id: int, payload: SplitAllocationUpdate) -> SplitAllocationOut:
    if _is_returned(db, actor, label_id):
        from app.services.payroll_returned_split_correction import correct_returned_split_allocation
        return correct_returned_split_allocation(db, actor=actor, label_id=label_id, payload=payload)
    for part in payload.parts:
        part.operation_name = part.operation_name.strip()
    if any(not part.operation_name for part in payload.parts):
        raise HTTPException(422, "Operation name is required")
    factory = selected_factory_code(actor)
    lock_period_schedule(db, factory)
    parent, labels, records, original = _group(db, label_id, factory)
    discovered = (parent.id, original.payroll_period_id, original.scanned_at, [label.id for label in labels])
    # Match existing payroll period -> label -> record lock order, including
    # periods covering a work date that has not yet been assigned to a period.
    periods = db.query(PayrollPeriod).filter(
        PayrollPeriod.factory_code == factory,
        or_(PayrollPeriod.id == original.payroll_period_id,
            (PayrollPeriod.start_date <= original.scanned_at) & (PayrollPeriod.end_date >= original.scanned_at)),
    ).order_by(PayrollPeriod.id).populate_existing().with_for_update().all()
    if any(period.status != "open" for period in periods):
        raise HTTPException(409, "The payroll period for this work is no longer open")
    parent, labels, records, original = _group(db, label_id, factory, lock=True)
    if discovered != (parent.id, original.payroll_period_id, original.scanned_at, [label.id for label in labels]):
        raise HTTPException(409, "Split payroll assignment changed; reload")
    before = _view(db, parent, labels, records, original)
    parts = {part.label_id: part for part in payload.parts}
    if len(parts) != len(payload.parts) or set(parts) != {label.id for label in labels}:
        raise HTTPException(409, "Submit every split label exactly once")
    if sum(part.quantity for part in parts.values()) != parent.quantity:
        raise HTTPException(409, "Split pieces must equal the original QR quantity")
    if any(is_control_operation(label) != is_control_operation({"operation_name": parts[label.id].operation_name, "operation_code": label.operation_code}) for label in labels):
        raise HTTPException(409, "A saved correction cannot change Control review classification")
    # A repeated PATCH after a lost response is a readback, never another earning
    # or audit append. A stale request asking for different values is rejected.
    unchanged = all(all(getattr(parts[row.label_id], key) == getattr(row, key)
                        for key in ("employee_id", "quantity", "operation_name", "rate_per_piece")) for row in before.parts)
    if unchanged:
        return before
    if payload.revision != before.revision:
        raise HTTPException(409, "Split allocations changed; reload before editing")
    employees = {row.id: row for row in db.query(Employee).filter(
        Employee.id.in_([part.employee_id for part in parts.values()]),
        Employee.factory_code == factory, Employee.status == "active",
    ).order_by(Employee.id).populate_existing().with_for_update().all()}
    if set(employees) != {part.employee_id for part in parts.values()}:
        raise HTTPException(409, "Select active employees from this payroll factory")
    ordered = [parts[label.id] for label in labels]
    exact = [Decimal(part.quantity) * part.rate_per_piece for part in ordered]
    financial_inputs_unchanged = all(part.quantity == label.quantity and part.rate_per_piece == label.rate_per_piece
                                     for label, part in zip(labels, ordered))
    old_rates = {label.rate_per_piece for label in labels}
    preserve_total = len(old_rates) == 1 and all(part.rate_per_piece in old_rates for part in ordered)
    target = sum(row.total_amount for row in before.parts) if preserve_total else sum(exact).quantize(Decimal("0.01"))
    amounts = ([records[label.payroll_record_id].total_amount for label in labels] if financial_inputs_unchanged
               else [value.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for value in exact])
    pennies = int((target - sum(amounts)) * 100)
    if pennies < 0 or pennies > len(amounts):
        raise HTTPException(409, "Existing rounded payroll requires manual review")
    for index in sorted(range(len(amounts)), key=lambda i: exact[i] - amounts[i], reverse=True)[:pennies]:
        amounts[index] += Decimal("0.01")
    if any(amount >= Decimal("1000000000000") for amount in amounts):
        raise HTTPException(409, "Corrected payroll amount exceeds the supported limit")
    for label, part, amount in zip(labels, ordered, amounts):
        employee = employees[part.employee_id]
        department = db.get(Department, employee.department_id) if employee.department_id else None
        apply_split_part_correction(db, label=label, record=records[label.payroll_record_id], employee=employee,
                                    department_name=department.name if department else None, part=part, amount=amount)
    # Reuse the existing transaction-bound audit chain; it queues the append and
    # finalizes it with this single outer commit, without a second business writer.
    log_action(db, actor, "correct_split_allocation", "PayrollQrLabel", parent.id,
               old_value=before.model_dump(mode="json"),
               new_value={"reason": payload.reason, "parts": [part.model_dump(mode="json") for part in ordered], "amounts": [str(value) for value in amounts]})
    db.flush()
    result = _view(db, parent, labels, records, original)
    db.commit()
    return result


def _is_returned(db: Session, actor: User, label_id: int) -> bool:
    label = db.query(PayrollQrLabel).filter_by(id=label_id, factory_code=selected_factory_code(actor)).first()
    return bool(label and label.status == "available" and label.return_count)


def render_split_allocation_labels(db: Session, *, actor: User, label_id: int, token_for_label) -> str:
    from app.services.payroll_labels import split_label_card, split_labels_html
    view = read_split_allocation(db, actor=actor, label_id=label_id)
    cards = [split_label_card(db.get(PayrollQrLabel, part.label_id),
                              db.get(Employee, part.employee_id) if part.employee_id else None,
                              token_for_label(part.label_id)) for part in view.parts]
    return split_labels_html(cards)
