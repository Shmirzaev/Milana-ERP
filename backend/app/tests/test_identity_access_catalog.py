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
