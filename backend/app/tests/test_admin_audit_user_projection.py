from uuid import uuid4

from sqlalchemy import event

from app.models import AuditLog, User
from app.tests.conftest import TestSessionLocal, test_engine


def test_admin_audit_log_projects_only_serialized_user_columns(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        actor = User(
            name=f"Audit projection actor {marker}",
            email=f"audit-projection-{marker}@example.invalid",
            password_hash="must-not-be-selected",
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(actor)
        db.flush()
        db.add(AuditLog(
            user_id=actor.id,
            action="read",
            entity_type=f"AuditProjection{marker}",
            entity_id=7,
            new_value_json={"key": "value"},
        ))
        db.commit()
        actor_id = actor.id

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/audit-logs",
            params={"entity_type": f"AuditProjection{marker}", "page": 1, "page_size": 10},
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["user"] == {
        "id": actor_id,
        "name": f"Audit projection actor {marker}",
        "email": f"audit-projection-{marker}@example.invalid",
    }
    audit_reads = [statement for statement in statements if " from audit_logs " in statement]
    assert len(audit_reads) == 2, statements
    user_reads = [statement for statement in statements if " from users " in statement]
    assert len(user_reads) == 1, statements  # The authentication lookup; no deferred load.
    data_select = next(statement for statement in audit_reads if " limit " in statement)
    selected_columns = data_select.split(" from audit_logs", 1)[0]
    for unrelated in (
        "users.password_hash",
        "users.last_login_at",
        "users.last_seen_at",
        "users.access_policy",
        "users.extra_permissions",
    ):
        assert unrelated not in selected_columns
    assert " join roles " not in data_select
    assert " join departments " not in data_select
