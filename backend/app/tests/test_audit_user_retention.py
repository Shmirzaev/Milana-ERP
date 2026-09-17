"""Account removal must not rewrite immutable audit actors or related rows."""

import pytest


@pytest.mark.parametrize("hashed", [True, False], ids=["hashed", "legacy"])
def test_audited_user_must_be_deactivated_without_losing_history(client, auth_headers, hashed):
    from app.db.session import SessionLocal
    from app.models import AuditLog, Employee, Notification, User
    from app.services.audit import log_action, verify_audit_hash_chain

    response = client.post(
        "/api/users",
        json={"name": "Audit Actor", "email": "audit.actor@example.com", "password": "AuditActor!2026"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]
    with SessionLocal() as db:
        actor = db.get(User, user_id)
        employee = Employee(user_id=user_id, full_name="Audit Actor")
        notification = Notification(user_id=user_id, title="Keep", message="Retain on denied deletion")
        db.add_all([employee, notification])
        if hashed:
            audit = log_action(db, actor, "update", "User", user_id, new_value={"name": "Audit Actor"})
        else:
            audit = AuditLog(user_id=user_id, action="login", entity_type="User", entity_id=user_id)
            db.add(audit)
        db.commit()
        audit_id, employee_id, notification_id = audit.id, employee.id, notification.id
        original = (audit.user_id, audit.entry_hash, audit.prev_hash)
        count = db.query(AuditLog).count()
        assert verify_audit_hash_chain(db)["ok"] is hashed

    response = client.delete(f"/api/users/{user_id}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert "Deactivate" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.get(User, user_id).is_active
        assert db.get(Employee, employee_id).user_id == user_id
        assert db.get(Notification, notification_id).user_id == user_id
        assert db.query(AuditLog).count() == count
        audit = db.get(AuditLog, audit_id)
        assert (audit.user_id, audit.entry_hash, audit.prev_hash) == original
        assert verify_audit_hash_chain(db)["ok"] is hashed

    response = client.patch(f"/api/users/{user_id}", json={"is_active": False}, headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert not db.get(User, user_id).is_active
        audit = db.get(AuditLog, audit_id)
        assert (audit.user_id, audit.entry_hash, audit.prev_hash) == original
        assert verify_audit_hash_chain(db)["ok"] is hashed
    response = client.delete(f"/api/users/{user_id}", headers=auth_headers)
    assert response.status_code == 409, response.text
