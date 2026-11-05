"""Existing role creation, validation order and atomic audit contracts."""
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.schemas import AuditLog, Role
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


def counts(h):
    with h.db() as db:
        return db.query(Role).count(), db.query(AuditLog).count()


@pytest.mark.parametrize("actor,permissions", [
    ("wildcard", [" finance.view ", "finance.view", "sales.orders"]),
    ("super", ["*", "admin.super"]),
])
def test_role_and_audit_save_together_preserving_raw_name(identity_admin, actor, permissions):
    h = identity_admin
    name = " " + uuid4().hex + " "
    response = h.client.post('/api/roles', headers=h.actors[actor][1],
                             json={"name": name, "permissions": permissions})
    assert response.status_code == 201, response.text
    expected = ["finance.view", "sales.orders"] if actor == "wildcard" else ["*", "admin.super"]
    assert response.json() == {"id": response.json()["id"], "name": name, "permissions": expected}
    with h.db() as db:
        role = db.get(Role, response.json()["id"])
        assert (role.name, role.permissions) == (name, expected)
        audit = db.query(AuditLog).filter_by(entity_type="Role", entity_id=role.id).one()
        assert (audit.action, audit.user_id, audit.new_value_json) == ("create", h.actors[actor][0], {"name": name})
        assert audit.old_value_json is None
        assert audit.entry_hash is not None


@pytest.mark.parametrize("actor,name,permissions,status,detail", [
    (None, "R"*65, ["admin.super"], 401, "Not authenticated"),
    ("ordinary", "Super Admin", ["admin.super"], 403, "Missing permission. Need any of: ['*']"),
    ("manager", "Super Admin", ["admin.super"], 403, "Missing permission. Need any of: ['*']"),
    ("wildcard", "  sUpEr AdMiN ", ["admin.super"], 403, "Only a super admin can create the super admin role"),
    ("wildcard", "R"*65, ["admin.super"], 403, "Only a super admin can grant administrator access"),
    ("wildcard", "R"*65, ["*"], 403, "Only a super admin can grant administrator access"),
    ("wildcard", "R"*65, ["factory:ECO:finance.view"], 403, "Only Super Admin can configure another factory"),
    ("wildcard", "R"*65, ["factory:MIL:"], 400, "Invalid factory permission"),
    ("wildcard", "R"*65, [], 422, "Role name must be at most 64 characters"),
])
def test_role_creation_refusal_precedence_and_no_writes(identity_admin, actor, name, permissions, status, detail):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors[actor][1] if actor else {},
                             json={"name": name, "permissions": permissions})
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert counts(h) == before


def test_role_name_storage_boundary_and_duplicate_failure(identity_admin):
    h = identity_admin
    name = uuid4().hex * 2
    body = {"name": name, "permissions": []}
    response = h.client.post('/api/roles', headers=h.actors['super'][1], json=body)
    assert response.status_code == 201, response.text
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors['super'][1], json=body)
    assert (response.status_code, response.json()) == (409, {"detail": "Role name already exists"})
    assert counts(h) == before


def test_precommit_failure_rolls_back_role_and_audit_then_retry(identity_admin):
    h = identity_admin
    before = counts(h)
    body = {"name": uuid4().hex, "permissions": []}

    def fail_commit(session):
        raise RuntimeError('injected before commit')

    event.listen(h.db.class_, 'before_commit', fail_commit)
    try:
        response = h.client.post('/api/roles', headers=h.actors['super'][1], json=body)
    finally:
        event.remove(h.db.class_, 'before_commit', fail_commit)
    assert response.status_code == 500
    assert counts(h) == before
    response = h.client.post('/api/roles', headers=h.actors['super'][1], json=body)
    assert response.status_code == 201, response.text
    assert counts(h) == (before[0]+1, before[1]+1)


def test_super_admin_can_create_protected_name_and_known_grants_are_retained(identity_admin):
    h = identity_admin
    name = "  sUpEr AdMiN  "
    response = h.client.post('/api/roles', headers=h.actors['super'][1],
                             json={"name": name, "permissions": ["finance.view"]})
    assert response.status_code == 201, response.text
    assert response.json()['name'] == name
    assert response.json()['permissions'] == ["finance.view"]
