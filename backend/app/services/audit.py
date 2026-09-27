from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models import AuditLog, User


_AUDIT_LOCK_NAMESPACE = 1_096_107_092  # ASCII "AUDT", stable across processes.
_AUDIT_LOCK_RESOURCE = 1_128_808_777  # ASCII "CHAI".
_AUDIT_QUEUES = "audit.chain.queues"
_AUDIT_COMMITTED = "audit.chain.committed"
_AUDIT_ROLLED_BACK = "audit.chain.rolled_back"
_AUDIT_FINALIZED = "audit.chain.finalized"
_AUDIT_HOOKS = "audit.chain.hooks"
_AUDIT_HEADS = "audit.chain.heads"
_AUDIT_VERIFY_BATCH_SIZE = 250


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
    heads = db.info.get(_AUDIT_HEADS, {})
    committed = db.info.get(_AUDIT_COMMITTED, set())
    rolled_back = db.info.get(_AUDIT_ROLLED_BACK, set())
    was_committed = transaction in committed
    was_rolled_back = transaction in rolled_back
    committed.discard(transaction)
    rolled_back.discard(transaction)
    db.info.get(_AUDIT_FINALIZED, set()).discard(transaction)

    if transaction.nested and was_committed and not was_rolled_back and entries:
        queues.setdefault(transaction.parent, []).extend(entries)
    if transaction.nested and was_committed and not was_rolled_back:
        if transaction in heads:
            heads[transaction.parent] = heads[transaction]
    heads.pop(transaction, None)

    # Non-nested children are SQLAlchemy's internal flush transactions.  Only
    # the root ending makes every remaining queue unreachable and safe to drop.
    if transaction.parent is None:
        queues.clear()
        committed.clear()
        rolled_back.clear()
        db.info.get(_AUDIT_FINALIZED, set()).clear()
        heads.clear()


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
        entry.prev_hash = prev_hash
        entry.entry_hash = _audit_entry_hash(
            prev_hash=prev_hash,
            user_id=entry.user_id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            old_value=entry.old_value_json,
            new_value=entry.new_value_json,
        )
        prev_hash = entry.entry_hash
    db.add_all(entries)
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


def _install_sqlite_audit_hooks(db: Session) -> None:
    if db.info.get(_AUDIT_HOOKS):
        return
    # SQLite allocates and flushes audit rows immediately.  Keep the cached
    # chain head scoped to the SQLAlchemy transaction so rollback/savepoints
    # cannot make a later entry point at a discarded hash.
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
        entry = AuditLog(
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

    transaction = _current_session_transaction(db)
    _install_sqlite_audit_hooks(db)
    heads = db.info.setdefault(_AUDIT_HEADS, {})
    prev_hash = heads.get(transaction)
    if transaction not in heads:
        parent = transaction.parent
        while parent is not None and parent not in heads:
            parent = parent.parent
        prev_hash = heads[parent] if parent is not None else _latest_entry_hash(db)
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
        heads[transaction] = entry.entry_hash
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
            db.query(AuditLog.entry_hash)
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
    for row in qry.yield_per(_AUDIT_VERIFY_BATCH_SIZE):
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
