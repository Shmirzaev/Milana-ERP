"""Issue payroll QR labels with the original batch reads, validation and transaction."""
from app.models.people.payroll_service import _canonicalize_payroll_input, _issue_order_lookup

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.dt import utcnow
from app.core.order_reference import resolve_order_id
from app.libs.dto.people.payroll import PayrollQrLabelsIssueIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.payroll_factory_scope_service import production_order_factory_condition
from app.models.people.payroll_service import (
    _canonical_payroll_snapshot, _normalize_production_batch_no, _to_decimal, _work_qr_token,
)
from app.schemas import PayrollQrLabel, PayrollRecord, ProductionOrder, SewingFlow, User, WorkOrder
from app.schemas.people.payroll_qr_persistence import apply_payroll_qr_changes, stage_issue_qr_label








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
