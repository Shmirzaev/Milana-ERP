"""Current reset-request contract, before service extraction."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.deps import user_permissions
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.password_reset_service import password_reset_hash
from app.schemas import Notification, PasswordResetToken, Role, User
from app.tests.test_auth_login_characterization import login_database


@pytest.fixture
def h(login_database):
    factory = login_database
    with factory() as db:
        admin_role = Role(name=f"Reset admin {uuid4().hex}", permissions=["admin.users"])
        employee_role = Role(name=f"Reset employee {uuid4().hex}", permissions=["finance.view"])
        db.add_all([admin_role, employee_role])
        db.flush()
        users = {}
        for key, role, active in (("admin", admin_role, True), ("active", employee_role, True), ("inactive", employee_role, False)):
            user = User(name=f"Reset {key}", email=f"reset-{uuid4().hex}@example.com",
                        password_hash=hash_password("ResetBaseline!2026"), role_id=role.id,
                        factory_code="MIL", is_active=active)
            db.add(user)
            db.flush()
            users[key] = (user.id, user.email)
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, users, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def counts(h):
    factory, _, _ = h
    with factory() as db:
        return db.query(PasswordResetToken).count(), db.query(Notification).count()


def test_known_active_account_commits_token_and_admin_notice_before_email(h, monkeypatch):
    factory, users, client = h
    token = f"baseline-{uuid4().hex}"
    monkeypatch.setattr("app.models.password_reset_service.secrets.token_urlsafe", lambda _: token)
    delivered = []

    def send(email, name, url, user_id):
        with factory() as db:
            assert db.query(PasswordResetToken).filter_by(user_id=user_id, token_hash=password_reset_hash(token)).count() == 1
            assert db.query(Notification).filter_by(user_id=users["admin"][0], title="Password reset requested").count() == 1
        delivered.append((email, name, url, user_id))

    monkeypatch.setattr(auth, "send_password_email_safely", send)
    before = counts(h)
    with factory() as db:
        recipients = [user for user in db.query(User).filter(User.is_active.is_(True)).all()
                      if "*" in user_permissions(user) or "admin.users" in user_permissions(user)]
    response = client.post("/api/auth/forgot-password", json={"email": users["active"][1].upper()})
    assert (response.status_code, response.json()) == (200, {"message": "If this account exists, a reset link has been sent."})
    assert counts(h) == (before[0] + 1, before[1] + len(recipients))
    assert delivered == [(users["active"][1], "Reset active", delivered[0][2], users["active"][0])]
    assert delivered[0][2].endswith(f"/reset-password?token={token}")
    with factory() as db:
        reset = db.query(PasswordResetToken).filter_by(user_id=users["active"][0]).one()
        assert reset.used_at is None
        assert reset.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        notice = db.query(Notification).filter_by(user_id=users["admin"][0], title="Password reset requested").one()
        assert users["active"][1] in notice.message and token not in notice.message
        assert notice.link == "/admin/users"


@pytest.mark.parametrize("kind", ["missing", "inactive"])
def test_unknown_and_inactive_accounts_get_same_neutral_response_without_writes(h, kind, monkeypatch):
    _, users, client = h
    delivered = []
    monkeypatch.setattr(auth, "send_password_email_safely", lambda *args: delivered.append(args))
    email = users["inactive"][1] if kind == "inactive" else f"missing-{uuid4().hex}@example.com"
    before = counts(h)
    response = client.post("/api/session/forgot-password", json={"email": email})
    assert (response.status_code, response.json()) == (200, {"message": "If this account exists, a reset link has been sent."})
    assert counts(h) == before and delivered == []


def test_sixth_request_is_rate_limited_before_user_lookup(h):
    _, users, client = h
    before = counts(h)
    email = f"missing-{uuid4().hex}@example.com"
    for _ in range(5):
        assert client.post("/api/auth/forgot-password", json={"email": email}).status_code == 200
    blocked = client.post("/api/auth/forgot-password", json={"email": users["active"][1]})
    assert (blocked.status_code, blocked.json()) == (429, {"detail": "Too many password reset requests. Try again later."})
    assert int(blocked.headers["retry-after"]) > 0
    assert counts(h) == before


def test_shared_store_outage_returns_503_without_token_or_notice(h, monkeypatch):
    _, users, client = h
    before = counts(h)

    def unavailable():
        raise ConnectionError("test store unavailable")

    monkeypatch.setattr(auth, "get_shared_counter_store", unavailable)
    response = client.post("/api/auth/forgot-password", json={"email": users["active"][1]})
    assert (response.status_code, response.json()) == (503, {"detail": "Authentication is temporarily unavailable. Try again later."})
    assert counts(h) == before
