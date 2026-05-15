from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models import AuditLog, User
from app.services.audit import log_action


def test_audit_log_serializes_datetime_in_json_payload():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None

        payload = {
            "deadline": datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
            "assigned_to": user.id,
            "changes": [{"at": datetime(2026, 5, 20, 12, 30, tzinfo=timezone.utc)}],
        }
        log_action(db, user, "update", "WorkOrder", 123, new_value=payload)
        db.commit()

        row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert row is not None
        assert isinstance(row.new_value_json["deadline"], str)
        assert row.new_value_json["deadline"].startswith("2026-05-19T00:00:00")
        assert isinstance(row.new_value_json["changes"][0]["at"], str)
    finally:
        db.close()
