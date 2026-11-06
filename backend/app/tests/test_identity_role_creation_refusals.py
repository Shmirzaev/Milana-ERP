"""Fail-first coverage for the explicitly approved role-create refusal contract."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.libs.dto.catalog.catalog import RoleIn
from app.models.audit_service import verify_audit_hash_chain
from app.models.identity.roles_service import create_role
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database
from app.tests.test_admin_membership_delete_race import membership_postgres_sessions as membership_postgres_sessions
from app.tests.test_identity_admin_role_list import identity_admin as identity_admin


def counts(h):
    with h.db() as db:
        return db.query(Role).count(), db.query(AuditLog).count()


@pytest.mark.parametrize('permissions', [
    ['not.a.permission'], ['finance.view', 'not.a.permission'],
    ['factory:ECO:not.a.permission'], ['factory:BAD:finance.view'], ['factory:MIL:'],
])
def test_unknown_permissions_are_json_422_and_save_nothing(identity_admin, permissions):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors['super'][1],
                             json={'name': uuid4().hex, 'permissions': permissions})
    unknown = sorted(set(permissions) - {'finance.view'})
    assert (response.status_code, response.json()) == (422, {'detail': f'Unknown permissions: {unknown}'})
    assert response.headers['content-type'].startswith('application/json')
    assert counts(h) == before


@pytest.mark.parametrize('permissions', [[], [' finance.view ', 'finance.view'], ['factory:ECO:*', 'factory:ECO:admin.super']])
def test_valid_normalized_and_scoped_permissions_keep_existing_success(identity_admin, permissions):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors['super'][1],
                             json={'name': uuid4().hex, 'permissions': permissions})
    assert response.status_code == 201, response.text
    expected = ['finance.view'] if permissions and permissions[0].startswith(' ') else permissions
    assert response.json()['permissions'] == expected
    assert counts(h) == (before[0]+1, before[1]+1)


def test_duplicate_name_is_json_409_and_does_not_save_another_audit(identity_admin):
    h = identity_admin
    name = uuid4().hex
    payload = {'name': name, 'permissions': ['finance.view']}
    first = h.client.post('/api/roles', headers=h.actors['super'][1], json=payload)
    assert first.status_code == 201, first.text
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors['super'][1], json=payload)
    assert (response.status_code, response.json()) == (409, {'detail': 'Role name already exists'})
    assert response.headers['content-type'].startswith('application/json')
    assert counts(h) == before


def test_existing_permission_refusal_precedes_unknown_permission_validation(identity_admin):
    h = identity_admin
    before = counts(h)
    response = h.client.post('/api/roles', headers=h.actors['manager'][1],
                             json={'name': uuid4().hex, 'permissions': ['not.a.permission']})
    assert (response.status_code, response.json()) == (403, {'detail': "Missing permission. Need any of: ['*']"})
    assert counts(h) == before


def test_unrelated_integrity_failure_is_not_reported_as_duplicate(identity_admin):
    h = identity_admin
    before = counts(h)

    def fail_insert(session, flush_context, instances):
        if any(isinstance(row, Role) for row in session.new):
            raise IntegrityError('unrelated role insert failure', {}, ValueError('synthetic constraint'))

    event.listen(h.db.class_, 'before_flush', fail_insert)
    try:
        response = h.client.post('/api/roles', headers=h.actors['super'][1],
                                 json={'name': uuid4().hex, 'permissions': []})
    finally:
        event.remove(h.db.class_, 'before_flush', fail_insert)
    assert response.status_code == 500
    assert counts(h) == before


def test_postgres_concurrent_same_name_creates_one_role_and_one_audit(membership_postgres_sessions):
    factory = membership_postgres_sessions
    with factory() as db:
        role = Role(name=uuid4().hex, permissions=['*', 'admin.super'])
        actor = User(name='Role concurrency actor', email=uuid4().hex+'@example.com',
                     password_hash='unused', role=role, factory_code='MIL', is_active=True)
        db.add(actor)
        db.commit()
        actor_id = actor.id
    name = uuid4().hex
    barrier = Barrier(2)

    def create():
        with factory() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                create_role(db, RoleIn(name=name, permissions=['finance.view']), actor)
                return 201
            except HTTPException as exc:
                assert exc.detail == 'Role name already exists'
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(create) for _ in range(2)]
        assert sorted(result.result(timeout=20) for result in results) == [201, 409]
    with factory() as db:
        saved = db.query(Role).filter_by(name=name).one()
        assert db.query(AuditLog).filter_by(entity_type='Role', entity_id=saved.id).count() == 1
        assert verify_audit_hash_chain(db)['ok'] is True
