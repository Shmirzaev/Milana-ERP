from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import AuditLog, Department, Role, User
from app.services.audit import _AUDIT_VERIFY_BATCH_SIZE, _audit_entry_hash, verify_audit_hash_chain


@contextmanager
def _audit_chain_database(row_count: int):
    engine = create_engine("sqlite://")
    Role.__table__.create(engine)
    Department.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    with Session(engine) as db:
        previous = None
        rows = []
        for index in range(row_count):
            values = {
                "prev_hash": previous,
                "user_id": None,
                "action": "read",
                "entity_type": "StreamingAudit",
                "entity_id": index,
                "old_value": None,
                "new_value": {"index": index},
            }
            entry_hash = _audit_entry_hash(**values)
            rows.append(AuditLog(
                prev_hash=previous,
                entry_hash=entry_hash,
                user_id=None,
                action="read",
                entity_type="StreamingAudit",
                entity_id=index,
                new_value_json={"index": index},
            ))
            previous = entry_hash
        db.add_all(rows)
        db.commit()
        yield db, previous
    engine.dispose()


def test_audit_chain_verification_streams_unbounded_history_in_batches():
    with _audit_chain_database(_AUDIT_VERIFY_BATCH_SIZE * 2 + 1) as (db, final_hash):
        fetch_sizes = []

        def capture(_conn, _cursor, statement, _parameters, context, _executemany):
            if statement.lstrip().lower().startswith("select") and "audit_logs" in statement.lower():
                fetch_sizes.append(context.execution_options.get("yield_per"))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = verify_audit_hash_chain(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert result == {
            "ok": True,
            "checked": _AUDIT_VERIFY_BATCH_SIZE * 2 + 1,
            "last_valid_hash": final_hash,
            "first_mismatch": None,
        }
        assert fetch_sizes == [_AUDIT_VERIFY_BATCH_SIZE]
