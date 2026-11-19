from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.schemas import AuditLog, User
from app.schemas.core_persistence import (
    add_audit_log_row,
    add_audit_log_rows,
    apply_audit_entry_hashes,
    build_audit_log_row,
)


_AUDIT_LOCK_NAMESPACE = 1_096_107_092  # ASCII "AUDT", stable across processes.
_AUDIT_LOCK_RESOURCE = 1_128_808_777  # ASCII "CHAI".
_AUDIT_QUEUES = "audit.chain.queues"
_AUDIT_COMMITTED = "audit.chain.committed"
_AUDIT_ROLLED_BACK = "audit.chain.rolled_back"
_AUDIT_FINALIZED = "audit.chain.finalized"
_AUDIT_HOOKS = "audit.chain.hooks"


def _json_safe(value: Any) -> Any:
    """Convert Python objects into JSON-serializable primitives for audit logs."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _latest_entry_hash(db: Session) -> str | None:
    row = (
        db.query(AuditLog.entry_hash)
        .filter(AuditLog.entry_hash.isnot(None))
        .order_by(AuditLog.id.desc())
        .first()
    )
    return str(row[0]) if row and row[0] else None


def _audit_entry_hash(
    *,
    prev_hash: str | None,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    old_value: Any,
    new_value: Any,
) -> str:
    payload = {
        "prev_hash": prev_hash,
        "user_id": user_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_session_transaction(db: Session):
    transaction = db.get_nested_transaction() or db.get_transaction()
    if transaction is None:
        db.begin()
        transaction = db.get_transaction()
    return transaction


def _audit_transaction_marker(db: Session):
    return db.get_nested_transaction() or db.get_transaction()


def _mark_audit_transaction_committed(db: Session) -> None:
    transaction = _audit_transaction_marker(db)
    if transaction is not None:
        db.info.setdefault(_AUDIT_COMMITTED, set()).add(transaction)


def _mark_audit_transaction_rolled_back(db: Session) -> None:
    transaction = _audit_transaction_marker(db)
    if transaction is not None:
        db.info.setdefault(_AUDIT_ROLLED_BACK, set()).add(transaction)


def _finish_audit_transaction(db: Session, transaction) -> None:
    queues = db.info.get(_AUDIT_QUEUES, {})
    entries = queues.pop(transaction, [])
    committed = db.info.get(_AUDIT_COMMITTED, set())
    rolled_back = db.info.get(_AUDIT_ROLLED_BACK, set())
    was_committed = transaction in committed
    was_rolled_back = transaction in rolled_back
    committed.discard(transaction)
    rolled_back.discard(transaction)
    db.info.get(_AUDIT_FINALIZED, set()).discard(transaction)

    if transaction.nested and was_committed and not was_rolled_back and entries:
        queues.setdefault(transaction.parent, []).extend(entries)

    # Non-nested children are SQLAlchemy's internal flush transactions.  Only
    # the root ending makes every remaining queue unreachable and safe to drop.
    if transaction.parent is None:
        queues.clear()
        committed.clear()
        rolled_back.clear()
        db.info.get(_AUDIT_FINALIZED, set()).clear()


def _finalize_postgres_audits(db: Session) -> None:
    # before_commit also fires for SAVEPOINT releases.  A nested queue is moved
    # to its parent only after that SAVEPOINT is known to have committed.
    if db.get_nested_transaction() is not None:
        return
    transaction = db.get_transaction()
    queues = db.info.get(_AUDIT_QUEUES, {})
    entries = queues.get(transaction, []) if transaction is not None else []
    if not entries or transaction in db.info.setdefault(_AUDIT_FINALIZED, set()):
        return
    if db.connection().get_isolation_level().upper() != "READ COMMITTED":
        raise RuntimeError("Audit-chain serialization requires PostgreSQL READ COMMITTED isolation")

    # Flush every business mutation before taking the chain mutex.  The only
    # non-audit locks still needed below are AuditLog.user_id FK key-share
    # locks, so acquire those in stable order before the global mutex too.
    db.flush()
    actor_ids = sorted({entry.user_id for entry in entries if entry.user_id is not None})
    if actor_ids:
        (
            db.query(User.id)
            .filter(User.id.in_(actor_ids))
            .order_by(User.id)
            .with_for_update(read=True, key_share=True, of=User)
            .all()
        )
    db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
        {"namespace": _AUDIT_LOCK_NAMESPACE, "resource": _AUDIT_LOCK_RESOURCE},
    )

    prev_hash = _latest_entry_hash(db)
    for entry in entries:
        entry_hash = _audit_entry_hash(
            prev_hash=prev_hash,
            user_id=entry.user_id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_value=entry.old_value_json,
            new_value=entry.new_value_json,
        )
        apply_audit_entry_hashes(entry, prev_hash=prev_hash, entry_hash=entry_hash)
        prev_hash = entry_hash
    add_audit_log_rows(db, entries)
    db.flush()
    db.info[_AUDIT_FINALIZED].add(transaction)


def _install_postgres_audit_hooks(db: Session) -> None:
    if db.info.get(_AUDIT_HOOKS):
        return
    event.listen(db, "before_commit", _finalize_postgres_audits)
    event.listen(db, "after_commit", _mark_audit_transaction_committed)
    event.listen(db, "after_rollback", _mark_audit_transaction_rolled_back)
    event.listen(db, "after_transaction_end", _finish_audit_transaction)
    db.info[_AUDIT_HOOKS] = True


def log_action(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    """Queue one atomic audit append.

    On PostgreSQL READ COMMITTED sessions, the returned object remains
    transient (including a null ``id`` and hashes) until the outer transaction
    commits.  SQLite retains the legacy immediate-flush behavior.
    """
    safe_old = _json_safe(old_value) if old_value is not None else None
    safe_new = _json_safe(new_value) if new_value is not None else None
    if db.get_bind().dialect.name == "postgresql":
        transaction = _current_session_transaction(db)
        if transaction in db.info.setdefault(_AUDIT_FINALIZED, set()):
            raise RuntimeError("Cannot append an audit after this transaction's audit chain was finalized")
        # Preserve log_action's historical flush boundary for business rows,
        # but allocate audit IDs only after the outer transaction has finished
        # all domain locking.  This keeps ID order identical to chain order.
        db.flush()
        _install_postgres_audit_hooks(db)
        entry = build_audit_log_row(
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value_json=safe_old,
            new_value_json=safe_new,
        )
        db.info.setdefault(_AUDIT_QUEUES, {}).setdefault(transaction, []).append(entry)
        if commit:
            db.commit()
        return entry

    prev_hash = _latest_entry_hash(db)
    entry_hash = _audit_entry_hash(
        prev_hash=prev_hash,
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=safe_old,
        new_value=safe_new,
    )
    entry = add_audit_log_row(
        db,
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value_json=safe_old,
        new_value_json=safe_new,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def export_audit_hash_chain(db: Session, *, start_id: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 1000), 5000))
    qry = db.query(AuditLog).order_by(AuditLog.id.asc())
    if start_id is not None:
        qry = qry.filter(AuditLog.id >= int(start_id))
    rows = qry.limit(safe_limit).all()
    return [
        {
            "id": row.id,
            "prev_hash": row.prev_hash,
            "entry_hash": row.entry_hash,
            "user_id": row.user_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "old_value": row.old_value_json,
            "new_value": row.new_value_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def verify_audit_hash_chain(db: Session, *, start_id: int | None = None, limit: int | None = None) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 5000)) if limit is not None else None
    expected_prev: str | None = None
    qry = db.query(AuditLog).order_by(AuditLog.id.asc())
    if start_id is not None:
        prior = (
            db.query(AuditLog)
            .filter(AuditLog.id < int(start_id), AuditLog.entry_hash.isnot(None))
            .order_by(AuditLog.id.desc())
            .first()
        )
        expected_prev = prior.entry_hash if prior else None
        qry = qry.filter(AuditLog.id >= int(start_id))
    if safe_limit is not None:
        qry = qry.limit(safe_limit)

    checked = 0
    last_hash: str | None = expected_prev
    for row in qry.all():
        checked += 1
        if not row.entry_hash:
            return {
                "ok": False,
                "checked": checked,
                "last_valid_hash": last_hash,
                "first_mismatch": {
                    "id": row.id,
                    "reason": "missing_entry_hash",
                    "expected": None,
                    "actual": row.entry_hash,
                },
            }
        if row.prev_hash != expected_prev:
            return {
                "ok": False,
                "checked": checked,
                "last_valid_hash": last_hash,
                "first_mismatch": {
                    "id": row.id,
                    "reason": "prev_hash_mismatch",
                    "expected": expected_prev,
                    "actual": row.prev_hash,
                },
            }
        expected_entry_hash = _audit_entry_hash(
            prev_hash=row.prev_hash,
            user_id=row.user_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            old_value=row.old_value_json,
            new_value=row.new_value_json,
        )
        if row.entry_hash != expected_entry_hash:
            return {
                "ok": False,
                "checked": checked,
                "last_valid_hash": last_hash,
                "first_mismatch": {
                    "id": row.id,
                    "reason": "entry_hash_mismatch",
                    "expected": expected_entry_hash,
                    "actual": row.entry_hash,
                },
            }
        expected_prev = row.entry_hash
        last_hash = row.entry_hash

    return {"ok": True, "checked": checked, "last_valid_hash": last_hash, "first_mismatch": None}


ACTION_LABELS = {
    "add_package": "added a package",
    "add_package_scan": "scanned and added a package",
    "add_ready_packages": "added ready packages",
    "admin_repair_totals": "repaired production totals",
    "approve": "approved",
    "approve_disposal": "approved disposal",
    "approve_planning": "approved planning",
    "block": "blocked",
    "bulk_create": "bulk created",
    "change_" + "password": "changed account credential",
    "complete": "completed",
    "confirm": "confirmed",
    "create": "created",
    "create_work_orders": "created work orders",
    "delete": "deleted",
    "delivered": "marked delivered",
    "deliver": "marked delivered",
    "damaged": "marked damaged",
    "generate_invoice": "generated invoice",
    "mark_disposed": "marked disposed",
    "mark_shipped": "marked shipped",
    "mark_paid": "marked paid",
    "receive": "received",
    "receive_purchase_order_line": "received purchase order line",
    "receive_at_printing": "received at printing",
    "receive_at_sewing": "received at sewing",
    "receive_storage": "received in storage",
    "reject_disposal": "rejected disposal",
    "release_reservation": "released reservation",
    "request_disposal": "requested disposal",
    "reserve": "reserved",
    "reserve_stock": "reserved stock",
    "sell": "sold",
    "send_to_printing": "sent to printing",
    "send_to_sewing": "sent to sewing",
    "ship": "shipped",
    "start": "started",
    "transfer": "transferred",
    "unblock": "unblocked",
    "update": "updated",
    "update_status": "updated status",
    "update_profile": "updated profile",
    "upload_logo": "uploaded logo",
}



ENTITY_LABELS = {
    "Brand": "brand",
    "Bundle": "bundle",
    "Collection": "collection",
    "Customer": "customer",
    "CuttingRecord": "cutting record",
    "Department": "department",
    "Employee": "employee",
    "FinishedGoodsStock": "finished goods stock",
    "Invoice": "invoice",
    "Item": "inventory item",
    "Model": "model",
    "ModelBOM": "model BOM",
    "ModelImage": "model image",
    "ModelSize": "model size",
    "Package": "package",
    "Payment": "payment",
    "PayrollAdjustment": "payroll adjustment",
    "PayrollPeriod": "payroll period",
    "PayrollRecord": "payroll record",
    "PrintingRecord": "printing record",
    "ProductionOrder": "production order",
    "PurchaseOrder": "purchase order",
    "PurchaseOrderLine": "purchase order line",
    "PurchaseRequest": "purchase request",
    "PurchaseRequestLine": "purchase request line",
    "QualityCheck": "quality check",
    "SalesOrder": "sales order",
    "SewingAssignment": "sewing assignment",
    "SewingFlow": "sewing flow",
    "SewingRecord": "sewing record",
    "Shipment": "shipment",
    "StockBatch": "stock batch",
    "StockMovement": "stock movement",
    "StockReservation": "stock reservation",
    "Supplier": "supplier",
    "SystemSetting": "system setting",
    "Task": "task",
    "User": "user",
    "Warehouse": "warehouse",
    "WasteDisposalRequest": "waste disposal request",
    "WasteRecord": "waste record",
    "WorkOrder": "work order",
}



DETAIL_KEYS = (
    "order_no",
    "production_no",
    "work_order_no",
    "bundle_no",
    "package_no",
    "shipment_no",
    "invoice_no",
    "batch_no",
    "sku",
    "code",
    "name",
    "title",
    "full_name",
    "email",
)



def _sentence(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value



def _label_action(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " "))



def _label_entity(entity_type: str) -> str:
    return ENTITY_LABELS.get(entity_type, entity_type.replace("_", " ").lower())



def _pick_identifier(value: dict | None) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in DETAIL_KEYS:
        raw = value.get(key)
        if raw not in (None, ""):
            return str(raw)
    return None



def _changed_fields(old_value: dict | None, new_value: dict | None) -> list[dict]:
    old = old_value if isinstance(old_value, dict) else {}
    new = new_value if isinstance(new_value, dict) else {}
    keys = sorted(set(old.keys()) | set(new.keys()))
    changes = []
    for key in keys:
        before = old.get(key)
        after = new.get(key)
        if before == after and key in old and key in new:
            continue
        changes.append({"field": key, "from": before, "to": after})
    return changes



def _audit_summary(audit: AuditLog, user: User | None) -> tuple[str, str]:
    actor = user.name if user else "System"
    action = _label_action(audit.action)
    entity = _label_entity(audit.entity_type)
    identifier = _pick_identifier(audit.new_value_json) or _pick_identifier(audit.old_value_json)
    target = f"{entity} #{audit.entity_id}" if audit.entity_id is not None else entity
    if identifier:
        target = f"{target} ({identifier})"
    summary = _sentence(f"{actor} {action} {target}.")
    reason = "Check this event and nearby earlier events when investigating the root cause."
    changes = _changed_fields(audit.old_value_json, audit.new_value_json)
    if changes:
        names = ", ".join(c["field"].replace("_", " ") for c in changes[:4])
        if len(changes) > 4:
            names += f", plus {len(changes) - 4} more"
        reason = f"Changed fields: {names}."
    return summary, reason



def _parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
        if end_of_day:
            return datetime.combine(parsed.date(), time.max)
        return datetime.combine(parsed.date(), time.min)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date filter: {value}") from e



def list_audit_logs(
    db: Session,
    limit: int = 200,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
):
    qry = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    if user_id:
        qry = qry.filter(AuditLog.user_id == user_id)
    if entity_type:
        qry = qry.filter(AuditLog.entity_type == entity_type.strip())
    if entity_id is not None:
        qry = qry.filter(AuditLog.entity_id == entity_id)
    if action:
        qry = qry.filter(AuditLog.action == action.strip())
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to, end_of_day=True)
    if parsed_from:
        qry = qry.filter(AuditLog.created_at >= parsed_from)
    if parsed_to:
        qry = qry.filter(AuditLog.created_at <= parsed_to)
    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        qry = qry.filter(
            (AuditLog.action.ilike(like))
            | (AuditLog.entity_type.ilike(like))
            | (User.name.ilike(like))
            | (User.email.ilike(like))
        )
    total = qry.count() if include_total else 0
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.order_by(AuditLog.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size)
    else:
        qry = qry.order_by(AuditLog.id.desc()).limit(limit)
    rows = qry.all()
    out = []
    for audit, user in rows:
        summary, root_cause_hint = _audit_summary(audit, user)
        out.append(
            {
            "id": audit.id,
            "user_id": audit.user_id,
            "user_name": user.name if user else None,
            "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
            "action": audit.action,
            "action_label": _label_action(audit.action),
            "entity_type": audit.entity_type,
            "entity_label": _label_entity(audit.entity_type),
            "entity_id": audit.entity_id,
            "new_value": audit.new_value_json,
            "old_value": audit.old_value_json,
            "changed_fields": _changed_fields(audit.old_value_json, audit.new_value_json),
            "prev_hash": audit.prev_hash,
            "entry_hash": audit.entry_hash,
            "summary": summary,
            "root_cause_hint": root_cause_hint,
            "created_at": audit.created_at,
        }
        )
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out
