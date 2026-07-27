from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models import AuditLog, User
from app.services.audit import log_action, verify_audit_hash_chain


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
        assert row.entry_hash and len(row.entry_hash) == 64
    finally:
        db.close()


def test_audit_log_hash_chain_links_entries():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        first = log_action(db, user, "update", "AuditHashTest", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashTest", 2, new_value={"step": 2})
        db.commit()

        assert first.entry_hash and len(first.entry_hash) == 64
        assert second.entry_hash and len(second.entry_hash) == 64
        assert second.prev_hash == first.entry_hash
        assert second.entry_hash != first.entry_hash
    finally:
        db.close()


def test_audit_hash_chain_export_and_verify_endpoint(client, auth_headers):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        last = db.query(AuditLog.id).order_by(AuditLog.id.desc()).first()
        start_id = int(last[0]) + 1 if last else 1
        first = log_action(db, user, "create", "AuditHashExport", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashExport", 1, new_value={"step": 2})
        db.commit()
        first_id = int(first.id)
        second_id = int(second.id)
    finally:
        db.close()

    verify = client.get(f"/api/audit-logs/hash-chain/verify?start_id={start_id}", headers=auth_headers)
    assert verify.status_code == 200, verify.text
    assert verify.json()["ok"] is True
    assert verify.json()["checked"] >= 2

    exported = client.get(f"/api/audit-logs/hash-chain/export?start_id={start_id}&limit=2", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    rows = exported.json()["rows"]
    assert [row["id"] for row in rows] == [first_id, second_id]
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]


def test_audit_hash_chain_verify_reports_tampered_row():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        last = db.query(AuditLog.id).order_by(AuditLog.id.desc()).first()
        start_id = int(last[0]) + 1 if last else 1
        first = log_action(db, user, "create", "AuditHashTamper", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashTamper", 1, new_value={"step": 2})
        db.commit()
        second_id = int(second.id)

        second.action = "tampered"
        db.commit()
        result = verify_audit_hash_chain(db, start_id=start_id)
        assert result["ok"] is False
        assert result["first_mismatch"]["id"] == second_id
        assert result["first_mismatch"]["reason"] == "entry_hash_mismatch"

        second.action = "update"
        db.commit()
        assert verify_audit_hash_chain(db, start_id=start_id)["ok"] is True
        assert first.entry_hash and second.entry_hash
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
    assert row["entry_hash"] and len(row["entry_hash"]) == 64
    assert {"field": "status", "from": "waiting", "to": "blocked"} in row["changed_fields"]
    assert "Changed fields" in row["root_cause_hint"]
