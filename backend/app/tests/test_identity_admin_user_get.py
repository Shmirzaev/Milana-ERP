"""Existing single-user lookup behavior before Identity extraction."""
import pytest

from app.schemas import AuditLog, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


@pytest.mark.parametrize('actor,target', [('manager', 'super'), ('wildcard', 'ordinary'), ('super', 'manager')])
def test_lookup_retains_output_and_allows_inactive_other_factory_target(identity_admin, actor, target):
    h = identity_admin
    with h.db() as db:
        user = db.get(User, h.actors[target][0])
        user.is_active = False
        user.factory_code = 'ECO'
        db.commit()
        expected = {'id': user.id, 'name': user.name, 'email': user.email, 'role_id': user.role_id,
                    'department_id': None, 'factory_code': 'ECO', 'extra_permissions': [],
                    'access_policy': None, 'is_active': False, 'last_login_at': None, 'last_seen_at': None}
        audits = db.query(AuditLog).count()
    response = h.client.get(f'/api/users/{h.actors[target][0]}', headers=h.actors[actor][1])
    assert response.status_code == 200, response.text
    result = response.json()
    assert isinstance(result.pop('created_at'), str)
    assert result == expected
    with h.db() as db:
        assert db.query(AuditLog).count() == audits
        assert db.get(User, h.actors[actor][0]).last_seen_at is None


@pytest.mark.parametrize('actor,status,detail', [
    (None, 401, 'Not authenticated'),
    ('ordinary', 403, "Missing permission. Need any of: ['admin.users', '*']"),
    ('manager', 404, 'User not found'),
    ('super', 404, 'User not found'),
])
def test_lookup_permission_before_missing_target(identity_admin, actor, status, detail):
    h = identity_admin
    response = h.client.get('/api/users/2147483647', headers=h.actors[actor][1] if actor else {})
    assert (response.status_code, response.json()) == (status, {'detail': detail})
