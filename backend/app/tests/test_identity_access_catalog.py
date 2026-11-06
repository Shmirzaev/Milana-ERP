"""Existing access catalog visibility and grantability contracts."""
import pytest

from app.core.permission_catalog import PERMISSION_CATALOG
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


@pytest.mark.parametrize('actor', ['manager', 'wildcard', 'super'])
def test_catalog_retains_order_labels_and_grantability_without_writes(identity_admin, actor):
    h = identity_admin
    with h.db() as db:
        before = [db.query(model).count() for model in (AuditLog, Role, User)]
    response = h.client.get('/api/access-catalog', headers=h.actors[actor][1])
    assert response.status_code == 200, response.text
    own = {'admin.users', 'finance.view'} if actor == 'manager' else {'*'}
    assert response.json() == [
        {**row, 'grantable': actor == 'super' if row['key'] in {'*', 'admin.super'}
         else '*' in own or row['key'] in own} for row in PERMISSION_CATALOG
    ]
    with h.db() as db:
        assert [db.query(model).count() for model in (AuditLog, Role, User)] == before


@pytest.mark.parametrize('actor,status,detail', [
    (None, 401, 'Not authenticated'),
    ('ordinary', 403, "Missing permission. Need any of: ['admin.users', '*']"),
])
def test_catalog_authentication_and_permission_refusals(identity_admin, actor, status, detail):
    h = identity_admin
    response = h.client.get('/api/access-catalog', headers=h.actors[actor][1] if actor else {})
    assert (response.status_code, response.json()) == (status, {'detail': detail})


def test_direct_service_rejects_unprivileged_actor(identity_admin):
    from fastapi import HTTPException
    from app.models.identity.access_service import get_access_catalog
    with identity_admin.db() as db:
        actor = db.get(User, identity_admin.actors["ordinary"][0])
        with pytest.raises(HTTPException) as error:
            get_access_catalog(actor)
        assert error.value.status_code == 403


@pytest.mark.parametrize("actor_kind", ["manager", "super"])
def test_direct_service_rejects_inactive_privileged_actor(identity_admin, actor_kind):
    from fastapi import HTTPException
    from app.models.identity.access_service import get_access_catalog
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
            get_access_catalog(actor)
        assert (error.value.status_code, error.value.detail) == (401, "Inactive or unknown user")
        db.rollback()
    with h.db() as after:
        target = after.get(User, target_id)
        assert (target.name, target.email, target.is_active, after.query(AuditLog).count(), after.query(User).count()) == expected
