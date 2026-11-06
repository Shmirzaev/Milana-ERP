"""Current signed-in password-change contract, before service extraction."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.models.password_reset_service import password_reset_hash
from app.schemas import AuditLog, PasswordResetToken, User
from app.schemas.identity.user_persistence import add_password_reset_token
from app.tests.test_auth_login_characterization import login_database as login_database  # noqa: F401 - pytest fixture, used by name

OLD = "ChangeBefore!2026"
NEW = "ChangeAfter!2026"


@pytest.fixture
def h(login_database):
    factory = login_database
    raw_token = f"change-{uuid4().hex}"
    with factory() as db:
        user = User(name="Password owner", email=f"change-{uuid4().hex}@example.com",
                    password_hash=hash_password(OLD), factory_code="MIL", is_active=True)
        db.add(user)
        db.flush()
        user_id, email = user.id, user.email
        add_password_reset_token(db, user_id=user_id, token_hash=password_reset_hash(raw_token),
                                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, user_id, email, raw_token, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def snapshot(h):
    factory, user_id, _, _, _ = h
    with factory() as db:
        user = db.get(User, user_id)
        link = db.query(PasswordResetToken).filter_by(user_id=user_id).one()
        return (user.password_hash, user.tokens_valid_from, link.used_at,
                db.query(AuditLog).filter_by(action="change_password", entity_id=user_id).count())


def payload(current=OLD, new=NEW, confirm=None):
    return {"current_password": current, "new_password": new, "confirm_new_password": confirm or new}


@pytest.mark.parametrize("transport", ["bearer", "cookie"])
def test_success_invalidates_old_token_reset_link_and_persists_audit(h, transport):
    factory, user_id, email, raw_token, client = h
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    before = snapshot(h)
    response = client.post("/api/auth/change-password", json=payload(), headers=headers)
    assert (response.status_code, response.json()) == (200, {"message": "password_updated"})
    assert "set-cookie" not in response.headers
    after = snapshot(h)
    assert after[0] != before[0] and after[1] is not None and after[2] is not None
    assert after[3] == before[3] + 1
    with factory() as db:
        assert verify_password(NEW, db.get(User, user_id).password_hash)
        audit = db.query(AuditLog).filter_by(action="change_password", entity_type="User", entity_id=user_id).one()
        assert (audit.user_id, audit.new_value_json) == (user_id, {"credential_changed": True, "reset_links_invalidated": True})
    old_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert (old_me.status_code, old_me.json()) == (401, {"detail": "Token expired, please sign in again"})
    client.cookies.clear()
    assert client.post("/api/auth/login-json", json={"email": email, "password": OLD, "factory_code": "MIL"}).status_code == 401
    assert client.post("/api/auth/login-json", json={"email": email, "password": NEW, "factory_code": "MIL"}).status_code == 200
    reused = client.post("/api/auth/reset-password", json={"token": raw_token, "new_password": "AnotherChange!2026", "confirm_new_password": "AnotherChange!2026"})
    assert (reused.status_code, reused.json()) == (400, {"detail": "Invalid or expired reset link"})


@pytest.mark.parametrize("case,status,detail", [
    ("mismatch", 400, "New passwords do not match"),
    ("wrong-current", 400, "Current password is incorrect"),
    ("wrong-before-weak", 400, "Current password is incorrect"),
    ("weak", 400, "Password must be at least 12 characters, include a number."),
    ("inactive", 401, "Inactive or unknown user"),
])
def test_refusals_preserve_credential_token_and_audit(h, case, status, detail):
    factory, user_id, _, _, client = h
    token = create_access_token(user_id)
    if case == "inactive":
        with factory() as db:
            db.get(User, user_id).is_active = False
            db.commit()
    request = payload()
    if case == "mismatch":
        request["confirm_new_password"] = "DifferentChange!2026"
    elif case in ("wrong-current", "wrong-before-weak"):
        request["current_password"] = "wrong"
    if case in ("weak", "wrong-before-weak"):
        request["new_password"] = request["confirm_new_password"] = "weak"
    before = snapshot(h)
    response = client.post("/api/auth/change-password", json=request, headers={"Authorization": f"Bearer {token}"})
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert snapshot(h) == before
