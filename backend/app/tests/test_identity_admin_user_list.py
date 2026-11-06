"""Existing unpaginated admin user listing and authorization contracts."""
import pytest

from app.schemas import AuditLog, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


@pytest.mark.parametrize('actor', ['manager', 'wildcard', 'super'])
def test_list_includes_inactive_other_factory_and_protected_accounts_in_id_order(identity_admin, actor):
    h = identity_admin
    with h.db() as db:
        target = db.get(User, h.actors['ordinary'][0])
        target.is_active = False
        target.factory_code = 'ECO'
        db.commit()
        expected = {u.id: (u.name, u.email, u.role_id, u.department_id, u.factory_code,
                            u.extra_permissions, u.access_policy, u.is_active)
                    for u in db.query(User).all()}
        before_audits = db.query(AuditLog).count()
    response = h.client.get('/api/users', headers=h.actors[actor][1])
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row['id'] for row in rows] == sorted(expected)
    for row in rows:
        assert set(row) == {'id', 'name', 'email', 'role_id', 'department_id', 'factory_code',
                            'extra_permissions', 'access_policy', 'is_active', 'last_login_at',
                            'last_seen_at', 'created_at'}
        assert tuple(row[key] for key in ('name', 'email', 'role_id', 'department_id', 'factory_code',
                                          'extra_permissions', 'access_policy', 'is_active')) == expected[row['id']]
    with h.db() as db:
        assert db.query(AuditLog).count() == before_audits
        assert db.get(User, h.actors[actor][0]).last_seen_at is None


@pytest.mark.parametrize('actor,status,detail', [
    (None, 401, 'Not authenticated'),
    ('ordinary', 403, "Missing permission. Need any of: ['admin.users', '*']"),
])
def test_list_authentication_and_permission_refusals(identity_admin, actor, status, detail):
    h = identity_admin
    response = h.client.get('/api/users', headers=h.actors[actor][1] if actor else {})
    assert (response.status_code, response.json()) == (status, {'detail': detail})


def test_direct_service_rejects_unprivileged_actor(identity_admin):
    from fastapi import HTTPException
    from app.models.identity.users_service import list_users
    with identity_admin.db() as db:
        actor = db.get(User, identity_admin.actors["ordinary"][0])
        with pytest.raises(HTTPException) as error:
            list_users(db, actor)
        assert error.value.status_code == 403


@pytest.mark.parametrize("actor_kind", ["manager", "super"])
def test_direct_service_rejects_inactive_privileged_actor(identity_admin, actor_kind):
    from fastapi import HTTPException
    from app.models.identity.users_service import list_users
    h = identity_admin
    target_id = h.actors["ordinary"][0]
    with h.db() as setup:
        setup.get(User, h.actors[actor_kind][0]).is_active = False
        setup.commit()
    with h.db() as before:
        target = before.get(User, target_id)
        expected = (target.name, target.email, target.is_active, before.query(AuditLog).count(), before.query(User).count())
    with h.db() as db:
        actor = db.get(User, h.actors[actor_kind][0])
        with pytest.raises(HTTPException) as error:
            list_users(db, actor)
        assert (error.value.status_code, error.value.detail) == (401, "Inactive or unknown user")
        db.rollback()
    with h.db() as after:
        target = after.get(User, target_id)
        assert (target.name, target.email, target.is_active, after.query(AuditLog).count(), after.query(User).count()) == expected


@pytest.mark.parametrize("actor_kind", ["manager", "super"])
def test_direct_service_rejects_stale_deactivated_actor(identity_admin, actor_kind):
    from fastapi import HTTPException
    from app.models.identity.users_service import list_users
    h = identity_admin
    target_id = h.actors["ordinary"][0]
    with h.db() as before:
        target = before.get(User, target_id)
        expected = (target.name, target.email, target.is_active, before.query(AuditLog).count(), before.query(User).count())
    with h.db() as db:
        actor = db.get(User, h.actors[actor_kind][0])
        assert actor.is_active
        with h.db() as other:
            other.get(User, actor.id).is_active = False
            other.commit()
        assert actor.is_active
        with pytest.raises(HTTPException) as error:
            list_users(db, actor)
        assert (error.value.status_code, error.value.detail) == (401, "Inactive or unknown user")
        db.rollback()
    with h.db() as after:
        target = after.get(User, target_id)
        assert (target.name, target.email, target.is_active, after.query(AuditLog).count(), after.query(User).count()) == expected
