"""Current-session read and last-seen contract, before service extraction."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database  # noqa: F401 - pytest fixture, used by name


@pytest.fixture
def h(login_database):
    factory = login_database
    with factory() as db:
        role = Role(name=f"Me baseline {uuid4().hex}", permissions=["finance.view"])
        db.add(role)
        db.flush()
        user = User(name="Me candidate", email=f"me-{uuid4().hex}@example.com",
                    password_hash=hash_password("MeBaseline!2026"), role_id=role.id,
                    factory_code="MIL", extra_permissions=["factory:ECO:cutting.records"], is_active=True)
        db.add(user)
        db.commit()
        user_id, email, role_name = user.id, user.email, role.name

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, user_id, email, role_name, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def snapshot(h):
    factory, user_id, _, _, _ = h
    with factory() as db:
        user = db.get(User, user_id)
        return user.last_login_at, user.last_seen_at, db.query(AuditLog).count(), db.query(User).count()


@pytest.mark.parametrize("path,transport", [
    ("/api/auth/me", "bearer"), ("/api/session/me", "cookie"),
])
def test_read_returns_selected_factory_and_commits_only_last_seen(h, path, transport):
    _, user_id, email, role_name, client = h
    token = create_access_token(user_id, {"factory_code": "ECO"})
    headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    before = snapshot(h)
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sewing_band_id": None, "id": user_id, "name": "Me candidate", "email": email,
        "role": role_name, "department": None, "department_code": None,
        "extra_permissions": ["factory:ECO:cutting.records"], "permissions": ["cutting.records"],
        "factory_code": "ECO", "assigned_factory_code": "MIL",
        "available_factories": ["MIL", "ECO"], "access_configured": False,
    }
    after = snapshot(h)
    assert before[0] == after[0] is None and before[1] is None and after[1] is not None
    assert after[2:] == before[2:]


@pytest.mark.parametrize("case,status,detail", [
    ("missing", 401, "Not authenticated"),
    ("invalid", 401, "Invalid token"),
    ("inactive", 401, "Inactive or unknown user"),
    ("unassigned", 403, "This account is not assigned to the selected factory"),
])
def test_refusal_precedes_last_seen_write(h, case, status, detail):
    factory, user_id, _, _, client = h
    if case == "inactive":
        with factory() as db:
            db.get(User, user_id).is_active = False
            db.commit()
    headers = {}
    if case != "missing":
        token = "bad-token" if case == "invalid" else create_access_token(user_id, {"factory_code": "BST" if case == "unassigned" else "MIL"})
        headers = {"Authorization": f"Bearer {token}"}
    before = snapshot(h)
    response = client.get("/api/auth/me", headers=headers)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert snapshot(h) == before


def test_shared_store_outage_keeps_authenticated_session_read_available(h, monkeypatch):
    _, user_id, _, _, client = h

    def unavailable():
        raise ConnectionError("test store unavailable")

    monkeypatch.setattr(main, "get_shared_counter_store", unavailable)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {create_access_token(user_id)}"})
    assert response.status_code == 200
    assert response.json()["factory_code"] == "MIL"
