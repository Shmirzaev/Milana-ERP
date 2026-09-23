from uuid import uuid4

from sqlalchemy import event

from app.api.routes import auth as auth_routes
from app.models import User
from app.tests.conftest import TestSessionLocal, test_engine


def test_forgot_password_user_lookup_selects_only_fields_used_by_route(client, monkeypatch):
    email = f"reset-projection-{uuid4().hex[:10]}@example.com"
    with TestSessionLocal() as db:
        db.add(User(name="Reset projection user", email=email, password_hash="unused", is_active=True))
        db.commit()

    monkeypatch.setattr(auth_routes, "send_password_email_safely", lambda *_args, **_kwargs: None)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post("/api/auth/forgot-password", json={"email": email})
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "If this account exists, a reset link has been sent."}
    user_lookup = next(statement for statement in statements if "where users.email = ?" in statement)
    selected_columns = user_lookup.split(" from ", 1)[0]
    assert "users.id" in selected_columns
    assert "users.email" in selected_columns
    assert "users.name" in selected_columns
    assert "users.is_active" in selected_columns
    assert "users.password_hash" not in selected_columns
    assert "users.extra_permissions" not in selected_columns
    assert "users.access_policy" not in selected_columns
