"""Returned split metadata corrections; payroll history is read/locked only."""
import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.schemas import Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.schemas.people.payroll_split_persistence import apply_returned_split_part
from app.libs.dto.people.payroll_split_correction import SplitAllocationOut, SplitAllocationPartOut, SplitAllocationUpdate
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_operation_service import is_control_operation
from app.models.payroll_period_lock_service import lock_period_schedule


def _group(db, label_id, factory, *, lock=False):
    selected = db.query(PayrollQrLabel).filter_by(id=label_id, factory_code=factory).first()
    if not selected:
        raise HTTPException(404, "Payroll QR label not found")
    if not selected.split_from_label_id:
        raise HTTPException(409, "Select a returned split label")
    query = db.query(PayrollQrLabel).filter(
        PayrollQrLabel.factory_code == factory,
        or_(PayrollQrLabel.id == selected.split_from_label_id,
            PayrollQrLabel.split_from_label_id == selected.split_from_label_id),
    ).order_by(PayrollQrLabel.id)
    if lock:
        query = query.populate_existing().with_for_update()
    rows = query.all()
    parent = next((row for row in rows if row.id == selected.split_from_label_id), None)
    labels = [row for row in rows if row.split_from_label_id == selected.split_from_label_id]
    selected = next((row for row in labels if row.id == label_id), None)
    if (not parent or parent.status != "superseded" or not parent.payroll_record_id
            or len(labels) < 2 or not selected or selected.status != "available" or not selected.return_count):
        raise HTTPException(409, "Returned split allocation changed; reload")
    uids = [row.label_uid for row in labels]
    ids = [parent.payroll_record_id, *(row.payroll_record_id for row in labels if row.payroll_record_id)]
    history = db.query(PayrollRecord).filter(
        PayrollRecord.factory_code == factory,
        or_(PayrollRecord.id.in_(ids), PayrollRecord.scan_uid.in_(uids), PayrollRecord.original_scan_uid.in_(uids)),
    ).order_by(PayrollRecord.id)
    if lock:
        history = history.populate_existing().with_for_update()
    records = history.all()
    by_id = {row.id: row for row in records}
    original = by_id.get(parent.payroll_record_id)
    if not original or original.status != "voided":
        raise HTTPException(409, "Original split payroll history changed; reload")
    if parent.quantity <= 0 or parent.quantity != int(parent.quantity):
        raise HTTPException(409, "Original QR must contain whole pieces")
    for label in labels:
        linked = [row for row in records if row.scan_uid == label.label_uid or row.original_scan_uid == label.label_uid]
        if label.quantity <= 0 or label.quantity != int(label.quantity) or label.currency != original.currency:
            raise HTTPException(409, "Split label quantities or currency changed; reload")
        if label.status == "available":
            if (not label.return_count or label.payroll_record_id or not linked
                    or any(row.status != "voided" or row.scan_uid is not None for row in linked)):
                raise HTTPException(409, "Returned split history is inconsistent; reload")
        elif label.status == "scanned":
            record = by_id.get(label.payroll_record_id)
            if (not record or record.status not in {"recorded", "approved", "paid"}
                    or record.scan_uid != label.label_uid or record.quantity != label.quantity
                    or record.rate_per_piece != label.rate_per_piece or record.operation_name != label.operation_name
                    or record.currency != label.currency
                    or any(row.id != record.id and (row.status != "voided" or row.scan_uid is not None) for row in linked)):
                raise HTTPException(409, "Scanned split history is inconsistent; reload")
        else:
            raise HTTPException(409, "Split labels were divided again or closed; reload")
    if sum(row.quantity for row in labels) != parent.quantity:
        raise HTTPException(409, "Split pieces no longer equal the original QR quantity")
    return parent, labels, records, original


def _view(db, parent, labels, records, original):
    by_id = {row.id: row for row in records}
    employees = {row.id: row for row in db.query(Employee).filter(Employee.id.in_([
        by_id[label.payroll_record_id].employee_id for label in labels if label.status == "scanned"
    ])).all()}
    parts = []
    for label in labels:
        record = by_id.get(label.payroll_record_id) if label.status == "scanned" else None
        employee = employees.get(record.employee_id) if record else None
        if record and not employee:
            raise HTTPException(409, "Assigned employee no longer exists; reload")
        parts.append(SplitAllocationPartOut(
            label_id=label.id, label_uid=label.label_uid, employee_id=record.employee_id if record else None,
            employee_name=employee.full_name if employee else "", quantity=int(label.quantity),
            operation_name=label.operation_name or "", rate_per_piece=label.rate_per_piece.quantize(Decimal(".0001")),
            total_amount=record.total_amount.quantize(Decimal(".01")) if record else None,
            currency=label.currency, editable=record is None,
        ))
    fingerprint = {
        "parent": [parent.id, parent.quantity, parent.updated_at],
        "labels": [[row.id, row.updated_at, row.status, row.return_count, row.payroll_record_id] for row in labels],
        "history": [[row.id, row.updated_at, row.status, row.scan_uid, row.original_scan_uid, row.payroll_period_id] for row in records],
        "parts": [part.model_dump(mode="json") for part in parts],
    }
    revision = hashlib.sha256(json.dumps(fingerprint, default=str, sort_keys=True).encode()).hexdigest()
    return SplitAllocationOut(mode="returned", parent_label_id=parent.id, original_record_id=original.id,
                              total_quantity=int(parent.quantity), revision=revision, parts=parts)


def read_returned_split_allocation(db: Session, *, actor: User, label_id: int) -> SplitAllocationOut:
    return _view(db, *_group(db, label_id, selected_factory_code(actor)))


def correct_returned_split_allocation(db: Session, *, actor: User, label_id: int, payload: SplitAllocationUpdate) -> SplitAllocationOut:
    factory = selected_factory_code(actor)
    lock_period_schedule(db, factory)
    parent, labels, records, original = _group(db, label_id, factory)
    discovered = (parent.id, [row.id for row in labels], [(row.id, row.payroll_period_id) for row in records])
    period_ids = {row.payroll_period_id for row in records if row.payroll_period_id}
    # Match normal payroll period -> label -> record ordering. Historical period
    # status does not prohibit metadata edits: there are no earning writes here.
    db.query(PayrollPeriod).filter(PayrollPeriod.factory_code == factory, PayrollPeriod.id.in_(period_ids)).order_by(
        PayrollPeriod.id).populate_existing().with_for_update().all()
    parent, labels, records, original = _group(db, label_id, factory, lock=True)
    if discovered != (parent.id, [row.id for row in labels], [(row.id, row.payroll_period_id) for row in records]):
        raise HTTPException(409, "Split payroll assignment changed; reload")
    before = _view(db, parent, labels, records, original)
    parts = {part.label_id: part for part in payload.parts}
    if len(parts) != len(payload.parts) or set(parts) != {row.id for row in labels}:
        raise HTTPException(409, "Submit every split label exactly once")
    keys = ("employee_id", "quantity", "operation_name", "rate_per_piece")
    for row in before.parts:
        part = parts[row.label_id]
        if row.editable:
            part.operation_name = part.operation_name.strip()
        if row.editable and not part.operation_name:
            raise HTTPException(422, "Operation name is required")
        if row.editable and part.employee_id is not None:
            raise HTTPException(409, "Assign returned labels through normal scanning")
        if not row.editable and any(getattr(part, key) != getattr(row, key) for key in keys):
            raise HTTPException(409, "Scanned sibling allocations are read-only")
    if sum(part.quantity for part in parts.values()) != parent.quantity:
        raise HTTPException(409, "Split pieces must equal the original QR quantity")
    if any(is_control_operation(label) != is_control_operation({"operation_name": parts[label.id].operation_name,
                                                               "operation_code": label.operation_code}) for label in labels):
        raise HTTPException(409, "A saved correction cannot change Control review classification")
    if all(all(getattr(parts[row.label_id], key) == getattr(row, key) for key in keys) for row in before.parts):
        return before
    if payload.revision != before.revision:
        raise HTTPException(409, "Split allocations changed; reload before editing")
    for label, row in zip(labels, before.parts):
        if row.editable:
            apply_returned_split_part(db, label=label, part=parts[label.id])
    log_action(db, actor, "correct_returned_split_labels", "PayrollQrLabel", parent.id,
               old_value=before.model_dump(mode="json"),
               new_value={"reason": payload.reason, "parts": [parts[row.id].model_dump(mode="json") for row in labels]})
    db.flush()
    result = _view(db, parent, labels, records, original)
    db.commit()
    return result
