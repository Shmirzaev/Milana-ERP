"""Approved mixed policy: ordinary authorization survives; auth fails closed."""
import logging
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import main
from app.api.routes import auth
from app.core.security import create_access_token, hash_password
from app.core.shared_store import InMemorySharedCounterStore, SQLiteSharedCounterStore
from app.models.password_reset_service import create_password_reset_token
from app.schemas import AuditLog, PasswordResetToken, Role, User
from app.tests.conftest import TestSessionLocal


class Actors(tuple):
    def __repr__(self):
        return "<isolated test credentials>"


class UnavailableStore(InMemorySharedCounterStore):
    def _unavailable(self, *args):
        raise ConnectionError("private-counter-error-marker")

    increment = ttl = set = delete = _unavailable


@pytest.fixture
def actors():
    password = secrets.token_urlsafe(24) + "A!9"
    ids = {}
    with TestSessionLocal() as db:
        for name, permissions in [("admin", ["*"]), ("limited", ["sales.orders"])]:
            role = Role(name=f"Outage {name} {uuid4().hex}", permissions=permissions)
            db.add(role)
            db.flush()
            user = User(name=f"Outage {name}", email=f"outage-{uuid4().hex}@example.com",
                        password_hash=hash_password(password), role_id=role.id,
                        factory_code="MIL", is_active=True)
            db.add(user)
            db.flush()
            ids[name] = (user.id, user.email)
        db.commit()
    return Actors((ids, password))


def configure(monkeypatch, store, *, enabled=True):
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", enabled)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 1000)
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    monkeypatch.setattr(auth, "get_shared_counter_store", lambda: store)


def headers(actors, name="admin"):
    return {"Authorization": "Bearer " + create_access_token(actors[0][name][0])}


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/session/me", "/api/tasks", "/api/users"])
def test_ordinary_authenticated_reads_survive_and_warn(monkeypatch, actors, caplog, path):
    configure(monkeypatch, UnavailableStore())
    # In-process Alembic tests disable existing loggers in their global config.
    monkeypatch.setattr(main.log, "disabled", False)
    with caplog.at_level(logging.WARNING, logger="milana"):
        response = TestClient(main.app, raise_server_exceptions=False).get(path, headers=headers(actors))
    assert response.status_code == 200
    assert "global rate limiting skipped" in caplog.text.lower()
    assert "private-counter-error-marker" not in caplog.text


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/tasks"])
def test_outage_does_not_authenticate_anonymous_requests(monkeypatch, path):
    configure(monkeypatch, UnavailableStore())
    assert TestClient(main.app, raise_server_exceptions=False).get(path).status_code == 401


def test_outage_does_not_grant_missing_permissions(monkeypatch, actors):
    configure(monkeypatch, UnavailableStore())
    response = TestClient(main.app, raise_server_exceptions=False).get(
        "/api/users", headers=headers(actors, "limited"))
    assert response.status_code == 403


@pytest.mark.parametrize("enabled", [True, False], ids=["global-on", "global-off"])
@pytest.mark.parametrize("path", [
    "/api/auth/login", "/api/session/login", "/api/auth/token",
    "/api/auth/login-json", "/api/session/login-json",
    "/api/auth/forgot-password", "/api/session/forgot-password",
    "/api/auth/reset-password", "/api/session/reset-password",
])
def test_sensitive_actions_return_json_503_without_credential_changes(monkeypatch, actors, enabled, path):
    user_id, email = actors[0]["admin"]
    password = actors[1]
    with TestSessionLocal() as db:
        user = db.get(User, user_id)
        token = create_password_reset_token(db, user)
        original_hash = user.password_hash
        db.commit()
        original_audits = db.query(AuditLog).count()
        original_tokens = db.query(PasswordResetToken).count()
    configure(monkeypatch, UnavailableStore(), enabled=enabled)
    client = TestClient(main.app, raise_server_exceptions=False)
    if path.endswith(("/login", "/token")):
        response = client.post(path, data={"username": email, "password": password})
    elif path.endswith("/login-json"):
        response = client.post(path, json={"email": email, "password": password, "factory_code": "MIL"})
    elif path.endswith("/forgot-password"):
        response = client.post(path, json={"email": email})
    else:
        new_password = secrets.token_urlsafe(24) + "B!8"
        response = client.post(path, json={"token": token, "new_password": new_password,
                                          "confirm_new_password": new_password})
    assert response.status_code == 503
    assert isinstance(response.json().get("detail"), str) and response.json()["detail"]
    assert "private-counter-error-marker" not in response.text
    assert "set-cookie" not in response.headers
    with TestSessionLocal() as db:
        user = db.get(User, user_id)
        assert user.password_hash == original_hash
        assert user.last_login_at is None
        assert db.query(PasswordResetToken).count() == original_tokens
        assert db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id,
                                                  PasswordResetToken.used_at.is_not(None)).count() == 0
        assert db.query(AuditLog).count() == original_audits


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/auth/login"])
def test_store_initialization_failure_obeys_mixed_policy(monkeypatch, actors, path):
    def unavailable():
        raise OSError("private-counter-error-marker")

    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main, "get_shared_counter_store", unavailable)
    monkeypatch.setattr(auth, "get_shared_counter_store", unavailable)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = (client.get(path, headers=headers(actors)) if path.endswith("/me") else
                client.post(path, data={"username": actors[0]["admin"][1], "password": actors[1]}))
    assert response.status_code == (200 if path.endswith("/me") else 503)


def test_real_sqlite_path_fault_recovers_without_restart_and_limits_resume(monkeypatch, actors, tmp_path):
    path = tmp_path / "counters.db"
    backup = tmp_path / "counters.saved"
    store = SQLiteSharedCounterStore(f"sqlite:///{path.as_posix()}", prefix="outage-test")
    configure(monkeypatch, store)
    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.get("/api/auth/me", headers=headers(actors)).status_code == 200
    path.rename(backup)
    path.mkdir()
    try:
        assert client.get("/api/auth/me", headers=headers(actors)).status_code == 200
        assert client.get("/api/tasks", headers=headers(actors)).status_code == 200
        response = client.post("/api/auth/login", data={"username": actors[0]["admin"][1], "password": actors[1]})
        assert response.status_code == 503
    finally:
        path.rmdir()
        backup.rename(path)
    assert client.get("/api/auth/me", headers=headers(actors)).status_code == 200
    assert client.post("/api/auth/login", data={"username": actors[0]["admin"][1], "password": actors[1]}).status_code == 200
    store.clear_namespace("global-rate")
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 1)
    assert client.get("/api/auth/me", headers=headers(actors)).status_code == 200
    assert client.get("/api/auth/me", headers=headers(actors)).status_code == 429


@pytest.mark.parametrize("state", ["invalid", "disabled"])
def test_outage_preserves_credential_rejection(monkeypatch, actors, state):
    bearer = headers(actors)
    if state == "invalid":
        bearer = {"Authorization": "Bearer invalid-test-input"}
    else:
        with TestSessionLocal() as db:
            db.get(User, actors[0]["admin"][0]).is_active = False
            db.commit()
    configure(monkeypatch, UnavailableStore())
    assert TestClient(main.app, raise_server_exceptions=False).get("/api/auth/me", headers=bearer).status_code == 401


@pytest.mark.parametrize("operation", ["increment", "set", "delete"])
def test_late_login_counter_failure_is_503_before_session_issue(monkeypatch, actors, operation):
    store = InMemorySharedCounterStore()
    configure(monkeypatch, store, enabled=False)
    monkeypatch.setattr(auth.settings, "AUTH_MAX_FAILED_ATTEMPTS", 1)

    def unavailable(*args):
        raise ConnectionError("private-counter-error-marker")

    monkeypatch.setattr(store, operation, unavailable)
    password = actors[1] if operation == "delete" else "intentionally-invalid-input"
    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/auth/login", data={"username": actors[0]["admin"][1], "password": password})
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    with TestSessionLocal() as db:
        assert db.get(User, actors[0]["admin"][0]).last_login_at is None


def test_global_retry_ttl_failure_also_skips_limit(monkeypatch, actors):
    store = InMemorySharedCounterStore()
    configure(monkeypatch, store)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(store, "increment", lambda *args: 2)

    def unavailable(*args):
        raise ConnectionError("private-counter-error-marker")

    monkeypatch.setattr(store, "ttl", unavailable)
    assert TestClient(main.app, raise_server_exceptions=False).get("/api/auth/me", headers=headers(actors)).status_code == 200


def test_ordinary_task_write_survives_but_assignment_permission_is_enforced(monkeypatch, actors):
    configure(monkeypatch, UnavailableStore())
    client = TestClient(main.app, raise_server_exceptions=False)
    user_id = actors[0]["admin"][0]
    created = client.post("/api/tasks", headers=headers(actors),
                          json={"title": "Outage write regression", "assigned_to": user_id})
    assert created.status_code == 201
    assert client.get(f"/api/tasks/{created.json()['id']}", headers=headers(actors)).status_code == 200
    denied = client.post("/api/tasks", headers=headers(actors, "limited"),
                         json={"title": "Denied outage assignment", "assigned_to": user_id})
    assert denied.status_code == 403
