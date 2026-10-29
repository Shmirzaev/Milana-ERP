"""Item CREATE against the approved isolated migrated PostgreSQL target.

Source proposal only: execution requires the existing identity-pinned target
receipt and coordinator/QA release.  This module never targets production.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.api.routes.inventory import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.inventory.item_input import ItemIn
from app.models import audit_service
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, Role, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def role_actor(sessions, permissions):
    with sessions.begin() as db:
        role = Role(name='Item create ' + uuid4().hex, permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name='Item create actor', email=f'item-create-{uuid4().hex}@example.invalid',
                    password_hash='unused', factory_code='MIL', role_id=role.id, is_active=True)
        db.add(user)
        db.flush()
        return user.id


def client_for(sessions):
    app = FastAPI()
    app.include_router(router)
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    return TestClient(app, raise_server_exceptions=False)


def auth(actor_id):
    return {'Authorization': f'Bearer {create_access_token(actor_id)}'}


def item_values(**overrides):
    marker = uuid4().hex
    values = {'sku': ' PG-ITEM-' + marker + ' ', 'name': '  Fabric ' + marker + '  ',
              'category': 'fabric', 'unit': 'kg', 'default_cost': '1.23455',
              'reorder_level': '2.34567', 'track_batch': True, 'is_active': True,
              'image_url': '  https://example.invalid/item.png  ',
              'composition': [{'name': '  Cotton ', 'percentage': 0},
                              {'name': ' ', 'percentage': 20},
                              {'name': ' Wool ', 'percentage': 25}]}
    values.update(overrides)
    return values


def test_pg_item_create_normalized_row_and_same_session_audit(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    values = item_values()
    seen = []
    insert = stock_service.item_persistence.insert_item
    audit = stock_service.log_action
    def observe_insert(db, command):
        row = insert(db, command)
        assert row.id is not None and object_session(row) is db
        seen.append(db)
        return row
    def observe_audit(db, *args, **kwargs):
        assert seen == [db]
        return audit(db, *args, **kwargs)
    monkeypatch.setattr(stock_service.item_persistence, 'insert_item', observe_insert)
    monkeypatch.setattr(stock_service, 'log_action', observe_audit)
    with client_for(sessions) as client:
        response = client.post('/inventory/items', headers=auth(actor_id), json=values)
    assert response.status_code == 201, response.text
    item_id = response.json()['id']
    with sessions() as db:
        saved = db.get(Item, item_id)
        assert (saved.sku, saved.name, saved.category, saved.unit) == (
            values['sku'], values['name'].strip(), 'fabric', 'kg')
        assert (saved.default_cost, saved.reorder_level) == (Decimal('1.2346'), Decimal('2.3457'))
        assert (saved.track_batch, saved.is_active, saved.image_url) == (True, True, 'https://example.invalid/item.png')
        assert saved.composition_json == [{'name': 'Cotton', 'percentage': 0.0}, {'name': 'Wool', 'percentage': 25.0}]
        rows = db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='create').all()
        assert len(rows) == 1 and rows[0].user_id == actor_id
        assert rows[0].new_value_json == {'sku': values['sku']}
    assert len(seen) == 1
    chain(sessions)


def test_pg_auth_category_and_raw_sku_refusal_order(customer_pg_sessions):
    sessions = customer_pg_sessions
    allowed = role_actor(sessions, ['storage.items'])
    material_only = role_actor(sessions, ['storage.items', 'inventory.materials_only'])
    denied = role_actor(sessions, ['sales.view'])
    values = item_values()
    with sessions.begin() as db:
        row = Item(sku=values['sku'], name='Existing inactive ' + uuid4().hex, category='fabric', unit='kg',
                   default_cost=Decimal('0'), reorder_level=Decimal('0'), track_batch=False,
                   is_active=False, image_url=None, composition_json=[])
        db.add(row)
        db.flush()
        existing_id = row.id
    invalid_image = dict(values, image_url='javascript:alert(1)')
    with client_for(sessions) as client:
        assert client.post('/inventory/items', json=invalid_image).status_code == 401
        assert client.post('/inventory/items', headers=auth(denied), json=invalid_image).status_code == 403
        response = client.post('/inventory/items', headers=auth(material_only),
                               json=dict(invalid_image, category='accessory'))
        assert response.status_code == 403 and response.json()['detail'] == 'Only material inventory is available to this user'
        response = client.post('/inventory/items', headers=auth(allowed), json=invalid_image)
        assert response.status_code == 400 and response.json()['detail'] == 'SKU already exists'
        # Whitespace is part of the raw SKU; this is a distinct value, not a normalization request.
        unique = dict(values, sku=values['sku'].strip(), name='Unique ' + uuid4().hex)
        response = client.post('/inventory/items', headers=auth(allowed), json=unique)
        assert response.status_code == 201, response.text
    with sessions() as db:
        assert db.get(Item, existing_id).is_active is False
        assert db.query(Item).filter(Item.sku.in_([values['sku'], values['sku'].strip()])).count() == 2
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=existing_id).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='Item', action='create', user_id=allowed).count() == 1
    chain(sessions)


def test_pg_active_name_group_and_inactive_freeform_behavior(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    name = 'Grouped ' + uuid4().hex
    with sessions.begin() as db:
        existing = Item(sku='NAME-' + uuid4().hex, name=name, category='fabric', unit='kg',
                        default_cost=Decimal('0'), reorder_level=Decimal('0'),
                        track_batch=False, is_active=True, composition_json=[])
        db.add(existing)
        db.flush()
        existing_id = existing.id
    conflict = item_values(name='  ' + name.upper() + '  ', category='semi_finished')
    inactive = item_values(name='  ', category='custom-category', unit='custom-unit', is_active=False)
    with client_for(sessions) as client:
        response = client.post('/inventory/items', headers=auth(actor_id), json=conflict)
        assert response.status_code == 400 and response.json()['detail'] == 'Material name already exists'
        response = client.post('/inventory/items', headers=auth(actor_id), json=inactive)
        assert response.status_code == 201, response.text
        created = response.json()['id']
    with sessions() as db:
        assert db.query(Item).filter_by(sku=conflict['sku']).count() == 0
        saved = db.get(Item, created)
        assert (saved.name, saved.category, saved.unit, saved.is_active) == ('', 'custom-category', 'custom-unit', False)
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=existing_id).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=created, action='create', user_id=actor_id).count() == 1
    chain(sessions)


@pytest.mark.parametrize('point', ['audit_enqueue', 'audit_finalize', 'before_commit'])
def test_pg_item_audit_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    values = item_values()
    attempted = []
    original = stock_service.log_action
    def fail(*args, **kwargs):
        raise RuntimeError('injected Item create failure')
    def wrapped(db, actor, action, entity_type, entity_id, **kwargs):
        attempted.append(entity_id)
        original(db, actor, action, entity_type, entity_id, **kwargs)
        if point == 'audit_enqueue':
            fail()
        if point == 'before_commit':
            event.listen(db, 'before_commit', fail)
    with monkeypatch.context() as patch:
        patch.setattr(stock_service, 'log_action', wrapped)
        if point == 'audit_finalize':
            patch.setattr(audit_service, '_audit_entry_hash', fail)
        with client_for(sessions) as client:
            assert client.post('/inventory/items', headers=auth(actor_id), json=values).status_code == 500
    assert len(attempted) == 1
    with sessions() as db:
        assert db.query(Item).filter_by(sku=values['sku']).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=attempted[0]).count() == 0
    with client_for(sessions) as client:
        response = client.post('/inventory/items', headers=auth(actor_id), json=values)
    assert response.status_code == 201, response.text
    with sessions() as db:
        saved = db.get(Item, response.json()['id'])
        assert saved.sku == values['sku'] and saved.name == values['name'].strip()
        assert db.query(Item).filter_by(sku=values['sku']).count() == 1
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=saved.id, action='create', user_id=actor_id).count() == 1
    # PostgreSQL sequences need not roll back; no sequence equality is assumed.
    chain(sessions)


def test_pg_duplicate_sku_race_keeps_existing_integrity_error_semantics(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    sku = 'RACE-' + uuid4().hex
    barrier = Barrier(2)
    original = stock_service._item_payload
    def after_sku_check(payload):
        barrier.wait(timeout=10)
        return original(payload)
    monkeypatch.setattr(stock_service, '_item_payload', after_sku_check)
    def worker(index):
        with sessions() as db:
            actor = db.get(User, actor_id)
            payload = ItemIn(sku=sku, name=f'Race {index} {uuid4().hex}', category='fabric', unit='kg')
            try:
                return ('created', stock_service.create_item(db, payload, actor).id)
            except IntegrityError:
                db.rollback()
                return ('integrity_error', None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, i) for i in range(2)]
        results = [f.result(timeout=30) for f in futures]
    assert sorted(x[0] for x in results) == ['created', 'integrity_error']
    created = next(x[1] for x in results if x[0] == 'created')
    with sessions() as db:
        assert db.query(Item).filter_by(sku=sku).count() == 1
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=created, action='create', user_id=actor_id).count() == 1
    chain(sessions)
