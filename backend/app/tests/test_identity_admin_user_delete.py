"""Account deletion contracts before extraction, including reference/audit atomicity."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.api.routes import admin
from app.schemas import AuditLog, Employee, Notification, PasswordResetToken, Role, Task, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


def references(h, target):
    with h.db() as db:
        rows = [Employee(user_id=target, full_name='Identity reference'),
                Notification(user_id=target, title='Identity reference'),
                PasswordResetToken(user_id=target, token_hash=uuid4().hex,
                                   expires_at=datetime.now(timezone.utc)+timedelta(hours=1)),
                Task(title='Identity reference', assigned_to=target, created_by=target)]
        db.add_all(rows)
        db.commit()
        return [(type(row), row.id) for row in rows]


def snapshot(h, target, refs):
    with h.db() as db:
        values = []
        for model, row_id in [(User, target), *refs]:
            row = db.get(model, row_id)
            values.append({column.name: getattr(row, column.name) for column in model.__table__.columns} if row else None)
        return values, db.query(AuditLog).count()


def delete(h, actor, target):
    return h.client.delete(f'/api/users/{target}', headers=h.actors[actor][1] if actor else {})


@pytest.mark.parametrize('actor', ['manager', 'super'])
@pytest.mark.parametrize('active', [True, False])
def test_delete_unused_user_detaches_nullable_deletes_required_refs_and_audits_once(identity_admin, actor, active):
    h = identity_admin
    target = h.actors['ordinary'][0]
    with h.db() as db:
        db.get(User, target).is_active = active
        other = Notification(user_id=h.actors[actor][0], title='Other user notification')
        db.add(other)
        db.commit()
        other_id = other.id
    refs = references(h, target)
    response = delete(h, actor, target)
    assert response.status_code == 204 and response.content == b''
    with h.db() as db:
        assert db.get(User, target) is None
        employee = db.get(Employee, refs[0][1])
        assert employee.user_id is None and employee.full_name == 'Identity reference'
        assert db.get(Notification, refs[1][1]) is None
        assert db.get(PasswordResetToken, refs[2][1]) is None
        task = db.get(Task, refs[3][1])
        assert task.assigned_to is None and task.created_by is None and task.title == 'Identity reference'
        assert db.get(Notification, other_id).user_id == h.actors[actor][0]
        audit = db.query(AuditLog).filter_by(entity_type='User', entity_id=target, action='delete').one()
        assert audit.user_id == h.actors[actor][0] and audit.old_value_json is None and audit.new_value_json is None
        assert audit.entry_hash
    response = delete(h, actor, target)
    assert (response.status_code, response.json()) == (404, {'detail': 'User not found'})


@pytest.mark.parametrize('actor,status,detail', [
    (None, 401, 'Not authenticated'),
    ('ordinary', 403, "Missing permission. Need any of: ['admin.users', '*']"),
    ('manager', 404, 'User not found'),
])
def test_authentication_and_permission_precede_missing_target(identity_admin, actor, status, detail):
    response = delete(identity_admin, actor, 2147483647)
    assert (response.status_code, response.json()) == (status, {'detail': detail})


@pytest.mark.parametrize('actor', ['manager', 'super'])
def test_self_deletion_refused_before_protection_and_audit_history(identity_admin, actor):
    h = identity_admin
    target = h.actors[actor][0]
    refs = references(h, target)
    with h.db() as db:
        db.add(AuditLog(user_id=target, action='login', entity_type='User', entity_id=target))
        db.commit()
    before = snapshot(h, target, refs)
    response = delete(h, actor, target)
    assert (response.status_code, response.json()) == (400, {'detail': 'You cannot delete your own account'})
    assert snapshot(h, target, refs) == before


@pytest.mark.parametrize('kind', ['role_name', 'role_permission', 'extra_permission', 'access_policy', 'wildcard'])
@pytest.mark.parametrize('active', [True, False])
def test_non_super_manager_cannot_delete_protected_forms_before_history_cleanup(identity_admin, kind, active):
    h = identity_admin
    target = h.actors['ordinary'][0]
    refs = references(h, target)
    protect_target(h, target, kind, active)
    with h.db() as db:
        db.add(AuditLog(user_id=target, action='login', entity_type='User', entity_id=target))
        db.commit()
    before = snapshot(h, target, refs)
    response = delete(h, 'manager', target)
    assert (response.status_code, response.json()) == (403, {'detail': 'Only a super admin can delete administrator accounts'})
    assert snapshot(h, target, refs) == before


@pytest.mark.parametrize('active', [True, False])
def test_audit_history_blocks_deletion_without_touching_any_references(identity_admin, active):
    h = identity_admin
    target = h.actors['ordinary'][0]
    refs = references(h, target)
    with h.db() as db:
        db.get(User, target).is_active = active
        db.add(AuditLog(user_id=target, action='login', entity_type='User', entity_id=target))
        db.commit()
    before = snapshot(h, target, refs)
    response = delete(h, 'super', target)
    assert (response.status_code, response.json()) == (409, {'detail': 'User has audit history. Deactivate the account instead.'})
    assert snapshot(h, target, refs) == before


def test_last_wildcard_admin_refusal_precedes_history_check(identity_admin):
    h = identity_admin
    target, actor = h.actors['wildcard'][0], h.actors['super'][0]
    with h.db() as db:
        db.query(User).filter(User.id.notin_([target, actor])).update({'is_active': False})
        db.get(Role, h.roles['super']).permissions = ['admin.super', 'admin.users']
        db.add(AuditLog(user_id=target, action='login', entity_type='User', entity_id=target))
        db.commit()
    before = snapshot(h, target, [])
    response = delete(h, 'super', target)
    assert (response.status_code, response.json()) == (400, {'detail': 'Cannot delete the last active administrator'})
    assert snapshot(h, target, []) == before


def test_last_super_admin_guard_for_existing_direct_route_caller(identity_admin):
    h = identity_admin
    target, actor = h.actors['ordinary'][0], h.actors['super'][0]
    with h.db() as db:
        db.query(User).filter(User.id != target).update({'is_active': False})
        db.get(User, target).extra_permissions = ['admin.super']
        db.commit()
    # An authenticated active Super Admin would itself be another active member.
    with h.db() as db, pytest.raises(HTTPException) as refused:
        admin.delete_user(target, db, db.get(User, actor))
    assert (refused.value.status_code, refused.value.detail) == (400, 'Cannot delete the last active super administrator')


@pytest.mark.parametrize('error_kind', ['runtime', 'integrity'])
def test_precommit_failure_rolls_back_deletion_all_refs_and_audit_then_retry(identity_admin, error_kind):
    h = identity_admin
    target = h.actors['ordinary'][0]
    refs = references(h, target)
    before = snapshot(h, target, refs)

    def fail_commit(session):
        if error_kind == 'integrity':
            raise IntegrityError('injected before commit', {}, ValueError('unrelated constraint'))
        raise RuntimeError('injected before commit')

    event.listen(h.db.class_, 'before_commit', fail_commit)
    try:
        response = delete(h, 'manager', target)
    finally:
        event.remove(h.db.class_, 'before_commit', fail_commit)
    assert response.status_code == 500
    assert snapshot(h, target, refs) == before
    assert delete(h, 'manager', target).status_code == 204
    assert snapshot(h, target, refs)[1] == before[1]+1


def protect_target(h, target, kind, active):
    with h.db() as db:
        u = db.get(User, target)
        u.is_active = active
        if kind == 'role_name':
            role = db.query(Role).filter_by(name='  Super Admin  ').first()
            if role is None:
                role = Role(name='  Super Admin  ', permissions=[])
                db.add(role)
                db.flush()
            u.role_id = role.id
        elif kind == 'role_permission':
            db.get(Role, h.roles['ordinary']).permissions = ['admin.super']
        elif kind == 'extra_permission':
            u.extra_permissions = ['admin.super']
        elif kind == 'access_policy':
            u.access_policy = {'MIL': {'allow': ['admin.super']}}
        else:
            u.extra_permissions = ['*']
        db.commit()


@pytest.mark.parametrize('kind', ['role_name', 'role_permission', 'extra_permission', 'access_policy', 'wildcard'])
@pytest.mark.parametrize('active', [True, False])
def test_explicit_super_without_wildcard_can_delete_nonfinal_protected_account(identity_admin, kind, active):
    h = identity_admin
    target = h.actors['ordinary'][0]
    protect_target(h, target, kind, active)
    with h.db() as db:
        db.get(Role, h.roles['super']).permissions = ['admin.super', 'admin.users']
        db.commit()
    response = delete(h, 'super', target)
    assert response.status_code == 204, response.text
    with h.db() as db:
        assert db.get(User, target) is None
        assert db.query(AuditLog).filter_by(entity_type='User', entity_id=target, action='delete').count() == 1
