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


def test_audit_log_endpoint_returns_manager_summary_and_filters(client, auth_headers):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        log_action(
            db,
            user,
            "update",
            "WorkOrder",
            987,
            old_value={"status": "waiting", "deadline": "2026-06-01"},
            new_value={"status": "blocked", "deadline": "2026-06-03"},
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/audit-logs?include_total=true&entity_type=WorkOrder&entity_id=987&action=update",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    row = body["rows"][0]
    assert row["summary"].endswith("updated work order #987.")
    assert row["action_label"] == "updated"
    assert row["entity_label"] == "work order"
    assert {"field": "status", "from": "waiting", "to": "blocked"} in row["changed_fields"]
    assert "Changed fields" in row["root_cause_hint"]
