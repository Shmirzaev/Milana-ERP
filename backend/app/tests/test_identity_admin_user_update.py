"""Admin PATCH contracts before extraction, including every ordered business refusal."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import verify_password
from app.schemas import AuditLog, PasswordResetToken, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin

PASSWORD = 'AdminReplacement!2026'


def snapshot(h, user_id):
    with h.db() as db:
        u = db.get(User, user_id)
        return ({column.name: getattr(u, column.name) for column in User.__table__.columns},
                db.query(AuditLog).count(),
                [(t.id, t.used_at) for t in db.query(PasswordResetToken).filter_by(user_id=user_id).order_by(PasswordResetToken.id)])


def patch(h, actor, target, body):
    return h.client.patch(f'/api/users/{h.actors[target][0]}', headers=h.actors[actor][1], json=body)


def test_manager_updates_email_access_and_activation_atomically_with_audit(identity_admin):
    h = identity_admin
    target = h.actors['ordinary'][0]
    before = snapshot(h, target)
    email = f'{uuid4().hex}@example.com'
    body = {'name': ' Updated name ', 'email': ' '+email.upper()+' ', 'role_id': None,
            'extra_permissions': [' finance.view ', 'finance.view'],
            'access_policy': {'MIL': {'allow': ['finance.view'], 'deny': []}}, 'is_active': False}
    response = patch(h, 'manager', 'ordinary', body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['name'] == body['name'] and result['email'] == email
    assert result['role_id'] is None and result['is_active'] is False
    assert result['extra_permissions'] == ['finance.view']
    assert not {'password', 'password_hash', 'tokens_valid_from'} & result.keys()
    with h.db() as db:
        u = db.get(User, target)
        assert (u.name, u.email, u.is_active, u.extra_permissions) == (body['name'], email, False, ['finance.view'])
        assert u.password_hash == before[0]['password_hash']
        audit = db.query(AuditLog).filter_by(entity_type='User', entity_id=target, action='update').one()
        assert audit.user_id == h.actors['manager'][0]
        assert audit.old_value_json == {key: before[0][key] for key in ('role_id', 'department_id', 'name', 'email', 'factory_code', 'extra_permissions', 'access_policy')}
        expected = {**body, 'email': email, 'extra_permissions': ['finance.view']}
        assert audit.new_value_json == expected and audit.entry_hash
    response = patch(h, 'manager', 'ordinary', {'is_active': True})
    assert response.status_code == 200 and response.json()['is_active'] is True


@pytest.mark.parametrize('password', [None, ''])
def test_empty_password_and_omitted_fields_keep_credentials_but_still_audit(identity_admin, password):
    h = identity_admin
    target = h.actors['ordinary'][0]
    before = snapshot(h, target)
    response = patch(h, 'manager', 'ordinary', {'password': password})
    assert response.status_code == 200, response.text
    after = snapshot(h, target)
    assert after[0] == before[0] and after[1] == before[1]+1
    with h.db() as db:
        audit = db.query(AuditLog).filter_by(entity_type='User', entity_id=target).one()
        assert audit.new_value_json == {}


def test_admin_password_rotates_cutoff_and_unused_reset_links_in_same_commit(identity_admin):
    h = identity_admin
    target = h.actors['ordinary'][0]
    used_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with h.db() as db:
        for used in (None, used_at):
            db.add(PasswordResetToken(user_id=target, token_hash=uuid4().hex,
                                     expires_at=datetime.now(timezone.utc)+timedelta(hours=1), used_at=used))
        db.commit()
    response = patch(h, 'manager', 'ordinary', {'password': PASSWORD})
    assert response.status_code == 200, response.text
    with h.db() as db:
        u = db.get(User, target)
        assert verify_password(PASSWORD, u.password_hash) and u.tokens_valid_from is not None
        tokens = db.query(PasswordResetToken).filter_by(user_id=target).order_by(PasswordResetToken.id).all()
        assert tokens[0].used_at == u.tokens_valid_from
        assert tokens[1].used_at.replace(tzinfo=timezone.utc) == used_at
        audit = db.query(AuditLog).filter_by(entity_type='User', entity_id=target).one()
        assert audit.new_value_json == {'credential_changed': True, 'reset_links_invalidated': True}


def test_super_admin_changes_factory_and_revokes_old_session(identity_admin):
    h = identity_admin
    response = patch(h, 'super', 'ordinary', {'factory_code': ' eco '})
    assert response.status_code == 200 and response.json()['factory_code'] == 'ECO'
    with h.db() as db:
        assert db.get(User, h.actors['ordinary'][0]).tokens_valid_from is not None


@pytest.mark.parametrize('actor,target,body,status,detail', [
    ('ordinary', 'ordinary', {'name': 'No'}, 403, "Missing permission. Need any of: ['admin.users', '*']"),
    ('manager', 'manager', {'factory_code': 'XYZ', 'role_id': 2147483647}, 400, 'Factory must be MIL, BST, or ECO'),
    ('manager', 'manager', {'factory_code': 'ECO', 'role_id': 2147483647}, 403, "Only Super Admin can change a user's factory"),
    ('manager', 'manager', {'role_id': None, 'extra_permissions': ['sales.orders'], 'is_active': False}, 403, 'You cannot change your own role'),
    ('manager', 'manager', {'extra_permissions': ['sales.orders'], 'is_active': False}, 403, 'You cannot change your own additional access'),
    ('manager', 'manager', {'is_active': False, 'access_policy': {'MIL': {'allow': ['finance.view']}}}, 403, 'You cannot deactivate your own account'),
    ('manager', 'manager', {'access_policy': {'MIL': {'allow': ['finance.view']}}}, 403, 'You cannot change your own access'),
    ('manager', 'ordinary', {'role_id': 2147483647, 'extra_permissions': ['admin.super']}, 404, 'Role not found'),
    ('manager', 'ordinary', {'role_id': 'SUPER'}, 403, 'Only a super admin can assign administrator roles'),
    ('manager', 'ordinary', {'extra_permissions': ['factory:MIL:']}, 400, 'Invalid factory permission'),
    ('manager', 'ordinary', {'extra_permissions': ['factory:ECO:finance.view']}, 403, 'Only Super Admin can configure another factory'),
    ('manager', 'ordinary', {'extra_permissions': ['admin.super']}, 403, 'Only a super admin can grant administrator access'),
    ('manager', 'ordinary', {'extra_permissions': ['sales.orders']}, 403, "You cannot grant permissions you don't hold: ['sales.orders']"),
    ('manager', 'ordinary', {'department_id': 2147483647, 'password': 'weak'}, 404, 'Department not found'),
    ('manager', 'ordinary', {'access_policy': {'ECO': {'allow': ['admin.super']}}}, 400, 'Super Admin access is configured in the primary factory only'),
    ('manager', 'ordinary', {'access_policy': {'ECO': {'allow': ['finance.view']}}}, 403, 'Only Super Admin can configure another factory'),
    ('manager', 'ordinary', {'access_policy': {'MIL': {'allow': ['admin.super']}}}, 403, 'Only Super Admin can grant administrator access'),
    ('manager', 'ordinary', {'access_policy': {'MIL': {'allow': ['sales.orders']}}}, 403, "You cannot grant permissions you don't hold"),
    ('manager', 'super', {'password': 'weak'}, 403, 'Only a super admin can manage administrator accounts'),
    ('manager', 'ordinary', {'password': 'weak', 'name': 'N'*129}, 400, 'Password must be at least 12 characters, include a number.'),
    ('manager', 'ordinary', {'name': 'N'*129, 'email': 'e'*256}, 422, 'User name must be at most 128 characters'),
    ('manager', 'ordinary', {'email': 'e'*256}, 422, 'User email must be at most 255 characters'),
])
def test_patch_refusal_order_and_rollback(identity_admin, actor, target, body, status, detail):
    h = identity_admin
    if body.get('role_id') == 'SUPER':
        body = {**body, 'role_id': h.roles['super']}
    before = snapshot(h, h.actors[target][0])
    response = patch(h, actor, target, body)
    assert (response.status_code, response.json()) == (status, {'detail': detail})
    assert snapshot(h, h.actors[target][0]) == before


@pytest.mark.parametrize('actor,status,detail', [
    (None, 401, 'Not authenticated'),
    ('ordinary', 403, "Missing permission. Need any of: ['admin.users', '*']"),
    ('manager', 404, 'User not found'),
])
def test_missing_target_after_authentication_and_permission(identity_admin, actor, status, detail):
    h = identity_admin
    response = h.client.patch('/api/users/2147483647', headers=h.actors[actor][1] if actor else {}, json={'name': 'No'})
    assert (response.status_code, response.json()) == (status, {'detail': detail})


@pytest.mark.parametrize('kind', ['super', 'wildcard'])
@pytest.mark.parametrize('action', ['deactivate', 'demote'])
def test_cannot_remove_last_active_super_or_wildcard_admin(identity_admin, kind, action):
    h = identity_admin
    target = h.actors[kind][0]
    actor = h.actors['super'][0]
    with h.db() as db:
        db.query(User).filter(User.id.notin_([target, actor])).update({'is_active': False})
        if kind == 'wildcard':
            db.get(Role, h.roles['super']).permissions = ['admin.super', 'admin.users']
        db.commit()
    before = snapshot(h, target)
    response = patch(h, 'super', kind, {'is_active': False} if action == 'deactivate' else {'role_id': h.roles['ordinary']})
    expected = 'Cannot remove the last active super administrator' if kind == 'super' else 'Cannot remove the last active administrator'
    assert (response.status_code, response.json()) == (400, {'detail': expected})
    assert snapshot(h, target) == before


def test_precommit_failure_rolls_back_user_credentials_links_and_audit_then_retry(identity_admin):
    h = identity_admin
    target = h.actors['ordinary'][0]
    with h.db() as db:
        db.add(PasswordResetToken(user_id=target, token_hash=uuid4().hex,
                                 expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
        db.commit()
    before = snapshot(h, target)

    def fail_commit(session):
        raise RuntimeError('injected before commit')

    event.listen(h.db.class_, 'before_commit', fail_commit)
    try:
        response = patch(h, 'super', 'ordinary', {'name': 'After', 'password': PASSWORD, 'factory_code': 'ECO'})
    finally:
        event.remove(h.db.class_, 'before_commit', fail_commit)
    assert response.status_code == 500
    assert snapshot(h, target) == before
    response = patch(h, 'super', 'ordinary', {'name': 'After', 'password': PASSWORD, 'factory_code': 'ECO'})
    assert response.status_code == 200, response.text
    assert snapshot(h, target)[1] == before[1]+1


@pytest.mark.parametrize('kind', ['role_name', 'role_permission', 'extra_permission', 'access_policy', 'wildcard'])
@pytest.mark.parametrize('active', [True, False])
def test_non_super_manager_cannot_edit_any_protected_administrator_form(identity_admin, kind, active):
    h = identity_admin
    target = h.actors['ordinary'][0]
    with h.db() as db:
        user = db.get(User, target)
        user.is_active = active
        if kind == 'role_name':
            role = db.query(Role).filter_by(name='  Super Admin  ').first()
            if role is None:
                role = Role(name='  Super Admin  ', permissions=[])
                db.add(role)
                db.flush()
            user.role_id = role.id
        elif kind == 'role_permission':
            db.get(Role, h.roles['ordinary']).permissions = ['admin.super']
        elif kind == 'extra_permission':
            user.extra_permissions = ['admin.super']
        elif kind == 'access_policy':
            user.access_policy = {'MIL': {'allow': ['admin.super']}}
        else:
            user.extra_permissions = ['*']
        db.commit()
    before = snapshot(h, target)
    response = patch(h, 'manager', 'ordinary', {'name': 'No'})
    assert (response.status_code, response.json()) == (403, {'detail': 'Only a super admin can manage administrator accounts'})
    assert snapshot(h, target) == before


def test_manager_inventory_scope_cannot_be_removed_from_another_account(identity_admin):
    h = identity_admin
    with h.db() as db:
        db.get(Role, h.roles['manager']).permissions = ['admin.users', 'finance.view', 'inventory.materials_only']
        db.commit()
    before = snapshot(h, h.actors['ordinary'][0])
    response = patch(h, 'manager', 'ordinary', {'access_policy': {'MIL': {'allow': ['finance.view']}}})
    assert (response.status_code, response.json()) == (403, {'detail': 'You cannot remove your own inventory scope from another account'})
    assert snapshot(h, h.actors['ordinary'][0]) == before


def test_duplicate_email_failure_preserves_user_and_audit(identity_admin):
    h = identity_admin
    with h.db() as db:
        email = db.get(User, h.actors['manager'][0]).email
    before = snapshot(h, h.actors['ordinary'][0])
    response = patch(h, 'manager', 'ordinary', {'email': email, 'name': 'No'})
    assert response.status_code == 500
    assert snapshot(h, h.actors['ordinary'][0]) == before
