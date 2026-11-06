"""Issue payroll QR labels with the original batch reads, validation and transaction."""
from app.models.people.payroll_service import _canonicalize_payroll_input, _issue_order_lookup

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dt import utcnow
from app.core.order_reference import resolve_order_id
from app.libs.dto.people.payroll import (
    PayrollQrLabelBatchDeleteIn, PayrollQrLabelEditIn, PayrollQrLabelSplitIn, PayrollQrLabelsIssueIn,
)
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_factory_scope_service import production_order_factory_condition
from app.models.people.payroll_service import (
    _canonical_payroll_snapshot, _normalize_production_batch_no, _serialize_qr_label, _to_decimal, _work_qr_token,
)
from app.schemas import PayrollQrLabel, PayrollRecord, ProductionOrder, SewingFlow, User, WorkOrder
from app.schemas.people.payroll_qr_persistence import apply_payroll_qr_changes, stage_issue_qr_label
from app.schemas.people.payroll_qr_lifecycle_persistence import stage_delete_qr_labels, stage_split_qr_label








def issue_qr_labels(
    payload: PayrollQrLabelsIssueIn,
    db: Session,
    current: User,
):
    if not payload.labels:
        raise HTTPException(400, "At least one payroll QR label is required")
    issued_at = utcnow()
    factory_code = selected_factory_code(current)
    issued_ids: list[int] = []
    created_ids: list[int] = []
    created_label_uids: set[str] = set()
    existing_count = 0
    issued_labels: list[dict[str, str]] = []

    # Read request-scoped identities once.  Validation below still runs in the
    # original row order, but does not turn a 50-label issue into 100+ SELECTs.
    flow_ids = {int(row.sewing_flow_id) for row in payload.labels if row.sewing_flow_id is not None}
    work_order_ids = {int(row.work_order_id) for row in payload.labels if row.work_order_id is not None}
    production_order_ids = {
        int(row.production_order_id) for row in payload.labels if row.production_order_id is not None
    }
    flow_by_id = (
        {int(flow.id): flow for flow in db.query(SewingFlow).filter(
            SewingFlow.id.in_(flow_ids), SewingFlow.factory_code == factory_code,
        ).all()}
        if flow_ids else {}
    )
    work_order_by_id = (
        {int(work_order.id): work_order for work_order in db.query(WorkOrder).filter(
            WorkOrder.id.in_(work_order_ids),
        ).all()}
        if work_order_ids else {}
    )
    referenced_production_ids = production_order_ids | {
        int(work_order.production_order_id)
        for work_order in work_order_by_id.values()
    }
    normalized_uids = [row.label_uid.strip() for row in payload.labels]
    order_lookup = _issue_order_lookup(db, payload.labels)
    uid_values = {uid for uid in normalized_uids if uid and len(uid) <= 128}
    labels_by_uid = (
        {label.label_uid: label for label in db.query(PayrollQrLabel).filter(
            PayrollQrLabel.factory_code == factory_code,
            PayrollQrLabel.label_uid.in_(uid_values),
        ).all()}
        if uid_values else {}
    )
    inferred_uids: set[str] = set()
    for row in payload.labels:
        label_uid = row.label_uid.strip()
        if (
            row.production_order_id is None
            and row.production_no
            and label_uid not in labels_by_uid
            and label_uid not in inferred_uids
        ):
            inferred_uids.add(label_uid)
            try:
                referenced = resolve_order_id(db, "PO", row.production_no, lookup=order_lookup)
            except HTTPException:
                # Preserve the original row-order error from canonicalization.
                continue
            if referenced is not None:
                referenced_production_ids.add(int(referenced))
    factory_production_ids = (
        {
            int(production_id)
            for (production_id,) in db.query(ProductionOrder.id).filter(
                ProductionOrder.id.in_(referenced_production_ids),
                production_order_factory_condition(factory_code),
            ).all()
        }
        if referenced_production_ids else set()
    )
    new_label_uids: set[str] = set()
    for row in payload.labels:
        if row.sewing_flow_id is not None:
            flow = flow_by_id.get(int(row.sewing_flow_id))
            if not flow:
                raise HTTPException(404, "Sewing line was not found in this factory")
        work_order = work_order_by_id.get(int(row.work_order_id)) if row.work_order_id is not None else None
        if row.work_order_id is not None and not work_order:
            raise HTTPException(404, "Work order not found")
        if work_order:
            if int(work_order.production_order_id) not in factory_production_ids:
                raise HTTPException(404, "Work order was not found in this factory")
            if row.production_order_id is not None and int(work_order.production_order_id) != int(row.production_order_id):
                raise HTTPException(400, "Work order does not belong to the production order")
        if row.production_order_id is not None:
            if int(row.production_order_id) not in factory_production_ids:
                raise HTTPException(404, "Production order was not found in this factory")
        label_uid = row.label_uid.strip()
        if not label_uid or len(label_uid) > 128:
            raise HTTPException(400, "Invalid payroll QR label identifier")
        label = labels_by_uid.get(label_uid)
        is_new = label is None
        if is_new:
            label = stage_issue_qr_label(db, factory_code=factory_code, label_uid=label_uid)
            labels_by_uid[label_uid] = label
            new_label_uids.add(label_uid)
            values = row.model_dump(exclude={"label_uid"})
            _canonicalize_payroll_input(
                db,
                values,
                factory_code,
                lookup=order_lookup,
                factory_production_ids=factory_production_ids,
            )
            values.pop("raw_work_json", None)
            values["payload"] = _canonical_payroll_snapshot(
                db,
                row.payload,
                production_order_id=row.production_order_id,
                sales_order_id=row.sales_order_id,
                lookup=order_lookup,
            )
            apply_payroll_qr_changes(label, values)
            apply_payroll_qr_changes(label, {
                "batch_no": _normalize_production_batch_no(row.batch_no),
                "label_uid": label_uid,
                "currency": (row.currency or "UZS").upper()[:8],
                "copy_index": max(1, int(row.copy_index or 1)),
                "quantity": _to_decimal(row.quantity),
                "rate_per_piece": _to_decimal(row.rate_per_piece),
                "issued_by": current.id,
                "issued_at": issued_at,
            })
        else:
            # A shared process code must not make a different payable operation
            # silently appear issued. Rate/quantity corrections retain the UID;
            # a different operation name requires explicit identity review.
            if (
                row.operation_name
                and label.operation_name
                and row.operation_name.strip().casefold() != label.operation_name.strip().casefold()
            ):
                raise HTTPException(409, "Payroll QR identifier already belongs to another paid operation; refresh the issued labels")
            existing_count += 1
        if is_new:
            apply_payroll_qr_changes(label, {"status": "available", "payroll_record_id": None})

    # Flush identities, then re-read matching records after all label
    # validation/creation.  This preserves the old same-request duplicate UID
    # behavior and observes a record that appeared while preparation ran.
    db.flush()
    record_uids = set(labels_by_uid).intersection(uid_values)
    records_by_uid = (
        {record.scan_uid: record for record in db.query(PayrollRecord).filter(
            PayrollRecord.factory_code == factory_code,
            PayrollRecord.scan_uid.in_(record_uids),
        ).all()}
        if record_uids else {}
    )
    for row, label_uid in zip(payload.labels, normalized_uids):
        label = labels_by_uid[label_uid]
        active_record = records_by_uid.get(label_uid)
        is_new = label_uid in new_label_uids
        if active_record:
            apply_payroll_qr_changes(label, {"status": "scanned", "payroll_record_id": active_record.id,
                                          "last_scanned_at": active_record.scanned_at})
        elif is_new:
            apply_payroll_qr_changes(label, {"status": "available", "payroll_record_id": None})
        issued_ids.append(int(label.id))
        if is_new and label_uid not in created_label_uids:
            created_label_uids.add(label_uid)
            created_ids.append(int(label.id))
        issued_labels.append({"label_uid": label.label_uid, "qr_token": _work_qr_token(int(label.id))})
    if created_ids:
        log_action(
            db,
            current,
            "issue",
            "PayrollQrLabel",
            created_ids[0],
            new_value={"count": len(created_ids), "label_ids": created_ids[:100]},
        )
    db.commit()
    return {
        "issued_count": len(issued_ids),
        "created_count": len(created_ids),
        "existing_count": existing_count,
        "labels": issued_labels,
    }


def _assert_qr_label_never_scanned(db: Session, label: PayrollQrLabel) -> None:
    if (
        label.status != "available"
        or label.payroll_record_id is not None
        or label.last_scanned_at is not None
        or int(label.return_count or 0) > 0
    ):
        raise HTTPException(409, "Only never-scanned payroll QR labels can be edited or split")
    historical_record = (
        db.query(PayrollRecord.id)
        .filter(
            PayrollRecord.factory_code == label.factory_code,
            or_(
                PayrollRecord.scan_uid == label.label_uid,
                PayrollRecord.original_scan_uid == label.label_uid,
            ),
        )
        .first()
    )
    if historical_record:
        raise HTTPException(409, "Payroll QR labels with payroll history cannot be edited or split")


def _corrected_label_values(payload: PayrollQrLabelEditIn) -> tuple[str, Decimal]:
    operation_name = payload.operation_name.strip()
    if not operation_name:
        raise HTTPException(400, "Payroll QR operation name is required")
    rate = _to_decimal(payload.rate_per_piece)
    if rate < 0:
        raise HTTPException(400, "Payroll QR rate cannot be negative")
    return operation_name, rate


def edit_qr_label(
    label_id: int,
    payload: PayrollQrLabelEditIn,
    db: Session,
    current: User,
):
    label = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id == label_id,
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .one_or_none()
    )
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    _assert_qr_label_never_scanned(db, label)
    operation_name, rate = _corrected_label_values(payload)
    old_value = {
        "operation_name": label.operation_name,
        "rate_per_piece": str(label.rate_per_piece),
        "qr_token": _work_qr_token(int(label.id)),
    }
    apply_payroll_qr_changes(label, {
        "operation_name": operation_name, "rate_per_piece": rate, "payload": None,
    })
    log_action(
        db,
        current,
        "edit_unscanned_qr",
        "PayrollQrLabel",
        int(label.id),
        old_value=old_value,
        new_value={
            "operation_name": operation_name,
            "rate_per_piece": str(rate),
            "qr_token": _work_qr_token(int(label.id)),
        },
    )
    db.commit()
    db.refresh(label)
    return _serialize_qr_label(label, records={}, employees={}, departments={})


def split_qr_label(
    label_id: int,
    payload: PayrollQrLabelSplitIn,
    db: Session,
    current: User,
):
    label = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id == label_id,
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .one_or_none()
    )
    if not label:
        raise HTTPException(404, "Payroll QR label not found")
    _assert_qr_label_never_scanned(db, label)
    operation_name, rate = _corrected_label_values(payload)
    quantities = [int(quantity) for quantity in payload.quantities]
    if any(quantity <= 0 for quantity in quantities):
        raise HTTPException(400, "Every split quantity must be a positive whole number")
    original_quantity = _to_decimal(label.quantity)
    if sum(quantities) != original_quantity:
        raise HTTPException(409, "Split quantities must equal the original payroll QR quantity")

    copied_fields = {
        "production_order_id": label.production_order_id,
        "sales_order_id": label.sales_order_id,
        "work_order_id": label.work_order_id,
        "production_batch_id": label.production_batch_id,
        "model_id": label.model_id,
        "production_no": label.production_no,
        "sales_order_no": label.sales_order_no,
        "batch_no": label.batch_no,
        "model_code": label.model_code,
        "operation_section": label.operation_section,
        "operation_code": label.operation_code,
        "operation_name": operation_name,
        "sewing_flow_id": label.sewing_flow_id,
        "sewing_line_code": label.sewing_line_code,
        "sewing_line_name": label.sewing_line_name,
        "cutting_passport_id": label.cutting_passport_id,
        "cutting_passport_no": label.cutting_passport_no,
        "size": label.size,
        "rate_per_piece": rate,
        "currency": label.currency,
        "status": "available",
        "issued_by": current.id,
        "issued_at": utcnow(),
        "split_from_label_id": int(label.id),
    }
    children: list[PayrollQrLabel] = []
    for index, quantity in enumerate(quantities):
        child = stage_split_qr_label(
            db,
            factory_code=label.factory_code,
            label_uid=f"OERP-SPLIT-{uuid4().hex.upper()}",
            copy_index=max(1, int(label.copy_index or 1)) + index,
            quantity=Decimal(quantity),
            copied_fields=copied_fields,
        )
        children.append(child)

    old_value = {
        "label_uid": label.label_uid,
        "qr_token": _work_qr_token(int(label.id)),
        "operation_name": label.operation_name,
        "quantity": str(label.quantity),
        "rate_per_piece": str(label.rate_per_piece),
    }
    apply_payroll_qr_changes(label, {
        "status": "superseded", "superseded_at": utcnow(),
        "superseded_by": current.id, "payroll_record_id": None,
    })
    db.flush()
    new_value = {
        "operation_name": operation_name,
        "rate_per_piece": str(rate),
        "quantities": quantities,
        "child_label_ids": [int(child.id) for child in children],
        "child_qr_tokens": [_work_qr_token(int(child.id)) for child in children],
    }
    log_action(
        db,
        current,
        "split_unscanned_qr",
        "PayrollQrLabel",
        int(label.id),
        old_value=old_value,
        new_value=new_value,
    )
    db.commit()
    for child in children:
        db.refresh(child)
    return {
        "superseded_label_id": int(label.id),
        "labels": [
            _serialize_qr_label(child, records={}, employees={}, departments={})
            for child in children
        ],
    }


def delete_qr_label_batch(
    payload: PayrollQrLabelBatchDeleteIn,
    db: Session,
    current: User,
):
    label_ids = sorted({int(label_id) for label_id in payload.label_ids if int(label_id) > 0})
    if not label_ids:
        raise HTTPException(400, "At least one payroll QR label is required")

    labels = (
        db.query(PayrollQrLabel)
        .filter(
            PayrollQrLabel.id.in_(label_ids),
            PayrollQrLabel.factory_code == selected_factory_code(current),
        )
        .with_for_update()
        .all()
    )
    if len(labels) != len(label_ids):
        raise HTTPException(404, "One or more payroll QR labels were not found")

    requested_size = payload.size.strip()
    actual_sizes = {str(label.size or "-").strip() or "-" for label in labels}
    if actual_sizes != {requested_size}:
        raise HTTPException(409, "Payroll QR labels must belong to the same requested size")

    order_keys = {
        (
            label.production_order_id,
            str(label.production_no or "").strip(),
            str(label.sales_order_no or "").strip(),
        )
        for label in labels
    }
    if len(order_keys) != 1:
        raise HTTPException(409, "Payroll QR labels must belong to the same order")

    if any(
        label.status != "available"
        or label.payroll_record_id is not None
        or label.last_scanned_at is not None
        or int(label.return_count or 0) > 0
        for label in labels
    ):
        raise HTTPException(409, "Only never-scanned payroll QR labels can be deleted")

    label_uids = [label.label_uid for label in labels]
    historical_record = (
        db.query(PayrollRecord.id)
        .filter(
            PayrollRecord.factory_code == selected_factory_code(current),
            or_(
                PayrollRecord.scan_uid.in_(label_uids),
                PayrollRecord.original_scan_uid.in_(label_uids),
            ),
        )
        .first()
    )
    if historical_record:
        raise HTTPException(409, "Payroll QR labels with payroll history cannot be deleted")

    audit_label = min(labels, key=lambda label: int(label.id))
    audit_value = {
        "size": requested_size,
        "count": len(labels),
        "label_ids": label_ids[:100],
        "production_order_id": audit_label.production_order_id,
        "production_no": audit_label.production_no,
        "sales_order_no": audit_label.sales_order_no,
    }
    log_action(
        db,
        current,
        "delete_unscanned_batch",
        "PayrollQrLabel",
        int(audit_label.id),
        old_value=audit_value,
    )
    stage_delete_qr_labels(db, labels)
    db.commit()
    return {"deleted_count": len(labels), "size": requested_size}
