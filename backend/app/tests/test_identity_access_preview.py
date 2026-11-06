"""Access preview is read-only calculation, including grants the actor cannot save."""
import pytest

from app.core.permission_catalog import PERMISSION_KEYS
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


def body(h, **changes):
    return {'name': 'Preview', 'email': 'preview@example.com', 'role_id': h.roles['ordinary'], **changes}


def counts(h):
    with h.db() as db:
        return [db.query(model).count() for model in (AuditLog, Role, User)]


@pytest.mark.parametrize('actor', ['manager', 'wildcard', 'super'])
def test_preview_expands_wildcard_without_saving_or_enforcing_grant_rights(identity_admin, actor):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/users/access-preview', headers=h.actors[actor][1],
                             json=body(h, role_id=h.roles['wildcard'], password='ignored'))
    assert response.status_code == 200, response.text
    expanded = sorted(PERMISSION_KEYS - {'admin.super'})
    assert response.json() == {
        'MIL': {'permissions': ['*'], 'effective': expanded, 'available': True},
        'BST': {'permissions': [], 'effective': [], 'available': False},
        'ECO': {'permissions': [], 'effective': [], 'available': False},
    }
    assert counts(h) == before


def test_preview_primary_denies_secondary_grants_and_empty_factories(identity_admin):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/users/access-preview', headers=h.actors['manager'][1], json=body(
        h, extra_permissions=['factory:ECO:sales.orders'],
        access_policy={'MIL': {'deny': ['finance.view']}, 'ECO': {'allow': ['finance.view']}}))
    assert response.status_code == 200, response.text
    assert response.json() == {
        'MIL': {'permissions': [], 'effective': [], 'available': True},
        'BST': {'permissions': [], 'effective': [], 'available': False},
        'ECO': {'permissions': ['sales.orders', 'finance.view'], 'effective': ['finance.view', 'sales.orders'], 'available': True},
    }
    assert counts(h) == before


@pytest.mark.parametrize('actor,changes,status,detail', [
    (None, {'role_id': 2147483647}, 401, 'Not authenticated'),
    ('ordinary', {'role_id': 2147483647}, 403, "Missing permission. Need any of: ['admin.users', '*']"),
    ('manager', {'role_id': 2147483647, 'department_id': 2147483647, 'factory_code': 'XYZ'}, 404, 'Role not found'),
    ('manager', {'department_id': 2147483647, 'factory_code': 'XYZ'}, 404, 'Department not found'),
    ('manager', {'factory_code': 'XYZ'}, 400, 'Factory must be MIL, BST, or ECO'),
])
def test_preview_refusal_order_and_no_writes(identity_admin, actor, changes, status, detail):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/users/access-preview', headers=h.actors[actor][1] if actor else {},
                             json=body(h, **changes))
    assert (response.status_code, response.json()) == (status, {'detail': detail})
    assert counts(h) == before


def test_super_admin_subject_is_available_in_every_factory(identity_admin):
    h = identity_admin
    response = h.client.post('/api/users/access-preview', headers=h.actors['manager'][1],
                             json=body(h, role_id=h.roles['super']))
    assert response.status_code == 200, response.text
    assert response.json() == {factory: {'permissions': ['*', 'admin.super'],
                                        'effective': sorted(PERMISSION_KEYS), 'available': True}
                               for factory in ('MIL', 'BST', 'ECO')}
