"""Role-list contracts captured before extraction, on both database engines."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database


@pytest.fixture
def identity_admin(login_database):
    factory = login_database
    actors, roles = {}, {}
    with factory() as db:
        for key, permissions in {
            "manager": ["admin.users", "finance.view"],
            "wildcard": ["*"], "super": ["*", "admin.super"],
            "ordinary": ["finance.view"],
        }.items():
            role = Role(name=f"Identity {key} {uuid4().hex}", permissions=permissions)
            db.add(role)
            db.flush()
            roles[key] = role.id
            user = User(name=f"Identity {key}", email=f"{uuid4().hex}@example.com",
                        password_hash="unused", role_id=role.id, factory_code="MIL", is_active=True)
            db.add(user)
            db.flush()
            actors[key] = (user.id, {"Authorization": "Bearer " + create_access_token(
                user.id, {"factory_code": "MIL"})})
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield SimpleNamespace(db=factory, actors=actors, roles=roles,
                              client=TestClient(app, raise_server_exceptions=False))
    finally:
        app.dependency_overrides[get_db] = previous


@pytest.mark.parametrize("actor", ["ordinary", "manager", "wildcard", "super"])
def test_every_authenticated_account_can_list_roles_without_writes(identity_admin, actor):
    h = identity_admin
    with h.db() as db:
        before = db.query(AuditLog).count()
        expected = {role.id: {"id": role.id, "name": role.name, "permissions": role.permissions}
                    for role in db.query(Role).all()}
    response = h.client.get("/api/roles", headers=h.actors[actor][1])
    assert response.status_code == 200, response.text
    assert {row["id"]: row for row in response.json()} == expected
    with h.db() as db:
        assert db.query(AuditLog).count() == before


@pytest.mark.parametrize("case,detail", [
    ("anonymous", "Not authenticated"),
    ("inactive", "Inactive or unknown user"),
])
def test_role_list_authentication_refusals(identity_admin, case, detail):
    h = identity_admin
    headers = {}
    if case == "inactive":
        with h.db() as db:
            db.get(User, h.actors["ordinary"][0]).is_active = False
            db.commit()
        headers = h.actors["ordinary"][1]
    response = h.client.get("/api/roles", headers=headers)
    assert (response.status_code, response.json()) == (401, {"detail": detail})
