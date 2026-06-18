from datetime import datetime, timedelta, timezone


def test_delete_user_detaches_existing_references(client, auth_headers):
    from app.db.session import SessionLocal
    from app.models import AuditLog, Employee, Notification, PasswordResetToken, User

    r = client.post(
        "/api/users",
        json={
            "name": "Delete Candidate",
            "email": "delete.candidate@example.com",
            "password": "DeleteCandidate!2026",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    db = SessionLocal()
    try:
        employee = Employee(user_id=user_id, full_name="Delete Candidate")
        audit = AuditLog(user_id=user_id, action="login", entity_type="User", entity_id=user_id)
        notification = Notification(user_id=user_id, title="Owned notification", message="delete me")
        reset_token = PasswordResetToken(
            user_id=user_id,
            token_hash="delete-candidate-token-hash",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([employee, audit, notification, reset_token])
        db.commit()
        employee_id = employee.id
        audit_id = audit.id
    finally:
        db.close()

    r = client.delete(f"/api/users/{user_id}", headers=auth_headers)
    assert r.status_code == 204, r.text

    db = SessionLocal()
    try:
        assert db.get(User, user_id) is None
        assert db.get(Employee, employee_id).user_id is None
        assert db.get(AuditLog, audit_id).user_id is None
        assert db.query(Notification).filter(Notification.user_id == user_id).count() == 0
        assert db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).count() == 0
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "delete",
                AuditLog.entity_type == "User",
                AuditLog.entity_id == user_id,
            )
            .count()
            == 1
        )
    finally:
        db.close()
