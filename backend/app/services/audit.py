from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditLog, User


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
    safe_old = _json_safe(old_value) if old_value is not None else None
    safe_new = _json_safe(new_value) if new_value is not None else None
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
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value_json=safe_old,
        new_value_json=safe_new,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    db.add(entry)
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
