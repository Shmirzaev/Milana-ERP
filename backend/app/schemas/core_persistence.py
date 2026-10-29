"""Schema-owned persistence for the shared audit and notification rows.

These helpers own the mapped construction, the add and the hash-field mutation
of the rows the audit and notification services write. The transaction
coordinator, the audit queue, the hash algorithm, the advisory locks, the
savepoint semantics, the event listeners and the commit policy stay in
`app/models/audit_service.py` and `app/models/notifications_service.py`.
"""

from sqlalchemy.orm import Session

from app.schemas.core import AuditLog, Notification


def build_audit_log_row(
    *,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    old_value_json: dict | None,
    new_value_json: dict | None,
    prev_hash: str | None = None,
    entry_hash: str | None = None,
) -> AuditLog:
    """Build one audit row. The caller decides when it is added."""
    return AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value_json=old_value_json,
        new_value_json=new_value_json,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


def add_audit_log_row(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    old_value_json: dict | None,
    new_value_json: dict | None,
    prev_hash: str | None = None,
    entry_hash: str | None = None,
) -> AuditLog:
    """Build and add one audit row to the caller's session."""
    row = build_audit_log_row(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value_json=old_value_json,
        new_value_json=new_value_json,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    db.add(row)
    return row


def add_audit_log_rows(db: Session, entries: list[AuditLog]) -> list[AuditLog]:
    """Add the finalized audit rows of one chain to the caller's session."""
    db.add_all(entries)
    return entries


def apply_audit_entry_hashes(entry: AuditLog, *, prev_hash: str | None, entry_hash: str) -> None:
    """Set the chained hash fields of one queued audit row."""
    entry.prev_hash = prev_hash
    entry.entry_hash = entry_hash


def add_notification_row(
    db: Session,
    *,
    user_id: int,
    title: str,
    message: str | None,
    link: str | None,
) -> Notification:
    """Add one notification row to the caller's session."""
    row = Notification(user_id=user_id, title=title, message=message, link=link)
    db.add(row)
    return row


def add_notification_rows(
    db: Session,
    *,
    user_ids: list[int],
    title: str,
    message: str | None,
    link: str | None,
) -> list[Notification]:
    """Add an ordered notification fan-out. The caller owns the flush boundary."""
    rows = [
        Notification(user_id=user_id, title=title, message=message, link=link)
        for user_id in user_ids
    ]
    db.add_all(rows)
    return rows
