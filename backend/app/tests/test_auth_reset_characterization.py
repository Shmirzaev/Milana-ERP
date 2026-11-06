"""Current password-reset completion contract, before service extraction."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.models.password_reset_service import password_reset_hash
from app.schemas import AuditLog, PasswordResetToken, User
from app.schemas.identity.user_persistence import add_password_reset_token
from app.tests.test_auth_login_characterization import login_database as login_database  # noqa: F401 - pytest fixture, used by name

OLD_PASSWORD = "ResetBefore!2026"
NEW_PASSWORD = "ResetAfter!2026"


@pytest.fixture
def h(login_database):
    factory = login_database
    raw_tokens = [f"reset-{uuid4().hex}" for _ in range(2)]
    with factory() as db:
        user = User(name="Reset candidate", email=f"reset-{uuid4().hex}@example.com",
                    password_hash=hash_password(OLD_PASSWORD), factory_code="MIL", is_active=True)
        db.add(user)
        db.flush()
        user_id = user.id
        for token in raw_tokens:
            add_password_reset_token(db, user_id=user_id, token_hash=password_reset_hash(token),
                                     expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, user_id, raw_tokens, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def payload(token, password=NEW_PASSWORD, confirm=None):
    return {"token": token, "new_password": password, "confirm_new_password": confirm or password}


def snapshot(h):
    factory, user_id, _, _ = h
    with factory() as db:
        user = db.get(User, user_id)
        tokens = db.query(PasswordResetToken).filter_by(user_id=user_id).order_by(PasswordResetToken.id).all()
        return (user.password_hash, user.tokens_valid_from,
                tuple(token.used_at for token in tokens),
                db.query(AuditLog).filter_by(action="reset_password", entity_id=user_id).count())


@pytest.mark.parametrize("path", ["/api/auth/reset-password", "/api/session/reset-password"])
def test_success_rotates_password_invalidates_siblings_and_old_bearer(h, path):
    factory, user_id, tokens, client = h
    old_bearer = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    assert client.get("/api/auth/me", headers=old_bearer).status_code == 200
    before = snapshot(h)
    response = client.post(path, json=payload(tokens[0]))
    assert (response.status_code, response.json()) == (200, {"message": "password_reset"})
    assert "set-cookie" not in response.headers
    after = snapshot(h)
    assert after[0] != before[0] and after[1] is not None
    assert all(used is not None for used in after[2]) and after[3] == before[3] + 1
    with factory() as db:
        assert verify_password(NEW_PASSWORD, db.get(User, user_id).password_hash)
        audit = db.query(AuditLog).filter_by(action="reset_password", entity_type="User", entity_id=user_id).one()
        assert audit.user_id == user_id
        assert audit.new_value_json == {"credential_changed": True, "reset_links_invalidated": True}
    assert client.get("/api/auth/me", headers=old_bearer).json() == {"detail": "Token expired, please sign in again"}
    reused = client.post(path, json=payload(tokens[1]))
    assert (reused.status_code, reused.json()) == (400, {"detail": "Invalid or expired reset link"})
    login = client.post("/api/auth/login-json", json={"email": _email(h), "password": NEW_PASSWORD, "factory_code": "MIL"})
    assert (login.status_code, login.json()) == (200, {"message": "logged_in"})


def _email(h):
    factory, user_id, _, _ = h
    with factory() as db:
        return db.get(User, user_id).email


@pytest.mark.parametrize("case,status,detail", [
    ("mismatch", 400, "New passwords do not match"),
    ("weak", 400, "Password must be at least 12 characters, include a number."),
    ("unknown", 400, "Invalid or expired reset link"),
    ("expired", 400, "Invalid or expired reset link"),
    ("used", 400, "Invalid or expired reset link"),
    ("inactive", 400, "Invalid or expired reset link"),
])
def test_refusal_order_detail_and_no_credential_write(h, case, status, detail):
    factory, user_id, tokens, client = h
    if case in ("expired", "used", "inactive"):
        with factory() as db:
            token = db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(tokens[0])).one()
            if case == "expired":
                token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            elif case == "used":
                token.used_at = datetime.now(timezone.utc)
            else:
                db.get(User, user_id).is_active = False
            db.commit()
    request = payload(tokens[0])
    if case == "mismatch":
        request["confirm_new_password"] = "DifferentPassword!2026"
    elif case == "weak":
        request["new_password"] = request["confirm_new_password"] = "weak"
    elif case == "unknown":
        request["token"] = "missing-token"
    before = snapshot(h)
    response = client.post("/api/auth/reset-password", json=request)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "set-cookie" not in response.headers
    assert snapshot(h) == before


def test_store_outage_precedes_password_validation_and_writes_nothing(h, monkeypatch):
    _, _, tokens, client = h

    def unavailable():
        raise ConnectionError("test store unavailable")

    monkeypatch.setattr(auth, "get_shared_counter_store", unavailable)
    before = snapshot(h)
    response = client.post("/api/auth/reset-password", json=payload(tokens[0], confirm="mismatch"))
    assert (response.status_code, response.json()) == (503, {"detail": "Authentication is temporarily unavailable. Try again later."})
    assert snapshot(h) == before
