"""Audit HTTP contracts on real isolated SQLite and PostgreSQL sessions."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models.audit_service import log_action
from app.schemas import AuditLog, Role, User
from app.tests.test_audit_chain_concurrency import audit_chain_postgres_sessions  # noqa: F401


@pytest.fixture(params=['sqlite', 'postgres'])
def audit_case(request):
    own_engine = None
    if request.param == 'postgres':
        sessions = request.getfixturevalue('audit_chain_postgres_sessions')[0]
    else:
        own_engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(own_engine)
        sessions = sessionmaker(bind=own_engine, autoflush=False, expire_on_commit=False)
    suffix = uuid4().hex
    with sessions() as db:
        db.query(AuditLog).delete(synchronize_session=False)
        db.query(User).delete(synchronize_session=False)
        db.query(Role).delete(synchronize_session=False)
        viewer_role = Role(name='Audit viewer '+suffix, permissions=['admin.audit'])
        denied_role = Role(name='No audit '+suffix, permissions=[])
        db.add_all([viewer_role, denied_role]); db.flush()
        actor = User(name='Audit Reader', email='audit-'+suffix+'@example.com', password_hash='unused', role_id=viewer_role.id, factory_code='MIL', is_active=True)
        foreign = User(name='Other Factory', email='foreign-'+suffix+'@example.com', password_hash='unused', role_id=denied_role.id, factory_code='BST', is_active=True)
        db.add_all([actor, foreign]); db.flush()
        first = log_action(db, actor, 'update', 'WorkOrder', 987,
                           old_value={'status': 'waiting', 'missing': None, 'same': 2, 'name': 'old'},
                           new_value={'status': 'done', 'same': 2, 'added': None, 'name': 'WO-987'})
        first.created_at = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        second = log_action(db, foreign, 'custom_action', 'odd_entity', 0, new_value={'title': 'FOREIGN'})
        second.created_at = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        third = log_action(db, None, 'create', 'Task', None)
        third.created_at = datetime(2026, 11, 3, 23, 59, 59, tzinfo=timezone.utc)
        db.commit()
        case = SimpleNamespace(sessions=sessions, actor_id=actor.id, foreign_id=foreign.id,
                               ids=[first.id, second.id, third.id])
    app = FastAPI(); app.include_router(router, prefix='/api')
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    case.headers = {'Authorization': 'Bearer '+create_access_token(case.actor_id)}
    case.denied = {'Authorization': 'Bearer '+create_access_token(case.foreign_id)}
    with TestClient(app) as client:
        case.client = client
        yield case
    if own_engine:
        own_engine.dispose()


def test_list_shape_order_global_visibility_and_outer_actor(audit_case):
    c = audit_case
    response = c.client.get('/api/audit-logs', headers=c.headers)
    assert response.status_code == 200
    rows = response.json()
    assert [r['id'] for r in rows] == list(reversed(c.ids))
    assert rows[0]['user'] is None and rows[0]['summary'] == 'System created task.'
    assert rows[1]['user']['name'] == 'Other Factory'
    assert rows[1]['entity_id'] == 0
    assert rows[1]['summary'] == 'Other Factory custom action odd entity #0 (FOREIGN).'
    assert rows[1]['action_label'] == 'custom action' and rows[1]['entity_label'] == 'odd entity'
    assert rows[2]['summary'] == 'Audit Reader updated work order #987 (WO-987).'
    assert rows[2]['changed_fields'] == [
        {'field': 'added', 'from': None, 'to': None},
        {'field': 'missing', 'from': None, 'to': None},
        {'field': 'name', 'from': 'old', 'to': 'WO-987'},
        {'field': 'status', 'from': 'waiting', 'to': 'done'},
    ]
    assert rows[2]['root_cause_hint'] == 'Changed fields: added, missing, name, status.'
    assert all(len(row['entry_hash']) == 64 for row in rows)


def test_pagination_clamps_and_legacy_limit(audit_case):
    c = audit_case
    response = c.client.get('/api/audit-logs', headers=c.headers,
                            params={'include_total': 'true', 'page': -4, 'page_size': 0})
    assert response.status_code == 200
    data = response.json()
    assert data['page'] == 1 and data['page_size'] == 1 and data['total'] == 3
    assert [r['id'] for r in data['rows']] == [c.ids[-1]]
    response = c.client.get('/api/audit-logs', headers=c.headers,
                            params={'include_total': 'true', 'page': 2, 'page_size': 2})
    assert [r['id'] for r in response.json()['rows']] == [c.ids[0]]
    assert c.client.get('/api/audit-logs?limit=0', headers=c.headers).json() == []
    assert len(c.client.get('/api/audit-logs?limit=1', headers=c.headers).json()) == 1
    assert c.client.get('/api/audit-logs?include_total=true&page_size=9999', headers=c.headers).json()['page_size'] == 500


def test_filters_dates_search_and_entity_zero(audit_case):
    c = audit_case
    for params, expected in [
        ({'user_id': c.foreign_id}, [c.ids[1]]),
        ({'user_id': 0}, list(reversed(c.ids))),
        ({'entity_type': ' WorkOrder ', 'entity_id': 987, 'action': ' update '}, [c.ids[0]]),
        ({'entity_id': 0}, [c.ids[1]]),
        ({'q': ' other factory '}, [c.ids[1]]),
        ({'q': 'ODD_ENTITY'}, [c.ids[1]]),
        ({'date_from': '2026-11-02', 'date_to': '2026-11-02'}, [c.ids[1]]),
        ({'date_from': '2026-11-03T23:59:59+00:00'}, [c.ids[2]]),
    ]:
        response = c.client.get('/api/audit-logs', headers=c.headers, params=params)
        assert response.status_code == 200, params
        assert [r['id'] for r in response.json()] == expected, params
    bad = c.client.get('/api/audit-logs?date_from=bad-date', headers=c.headers)
    assert bad.status_code == 400 and bad.json()['detail'] == 'Invalid date filter: bad-date'


def test_authorization_and_reads_leave_rows_and_hashes_unchanged(audit_case):
    c = audit_case
    def snapshot():
        with c.sessions() as db:
            return [(r.id, r.user_id, r.prev_hash, r.entry_hash, r.old_value_json, r.new_value_json)
                    for r in db.query(AuditLog).order_by(AuditLog.id)]
    before = snapshot()
    assert c.client.get('/api/audit-logs').status_code == 401
    assert c.client.get('/api/audit-logs', headers=c.denied).status_code == 403
    assert c.client.get('/api/audit-logs', headers=c.headers).status_code == 200
    assert c.client.get('/api/audit-logs/hash-chain/verify', headers=c.headers).json()['ok'] is True
    assert snapshot() == before
