"""Item UPDATE on the identity-pinned disposable PostgreSQL instance only."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.libs.dto.inventory.item_input import ItemIn
from app.models import audit_service
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_inventory_item_create_postgres import auth, client_for, item_values, role_actor


def make_item(sessions):
    with sessions.begin() as db:
        item = Item(sku='OLD-' + uuid4().hex, name='Old ' + uuid4().hex, category='fabric', unit='m',
                    default_cost=Decimal('2'), reorder_level=Decimal('3'), track_batch=True,
                    is_active=True, image_url=None, composition_json=[])
        db.add(item)
        db.flush()
        return item.id, item.sku, item.name


def test_pg_update_fields_same_session_and_chain(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    item_id, old_sku, old_name = make_item(sessions)
    values = item_values(name='  Материал 🧵  ')
    original = stock_service.item_persistence.update_item
    seen = []
    def observe(db, item, command):
        assert object_session(item) is db
        seen.append(db)
        return original(db, item, command)
    audit = stock_service.log_action
    def observe_audit(db, *args, **kwargs):
        assert seen == [db]
        return audit(db, *args, **kwargs)
    monkeypatch.setattr(stock_service.item_persistence, 'update_item', observe)
    monkeypatch.setattr(stock_service, 'log_action', observe_audit)
    with client_for(sessions) as client:
        response = client.patch(f'/inventory/items/{item_id}', headers=auth(actor_id), json=values)
    assert response.status_code == 200, response.text
    with sessions() as db:
        item = db.get(Item, item_id)
        assert (item.sku, item.name, item.category, item.unit) == (values['sku'], 'Материал 🧵', 'fabric', 'kg')
        assert (item.default_cost, item.reorder_level) == (Decimal('1.2346'), Decimal('2.3457'))
        assert (item.track_batch, item.is_active, item.image_url) == (True, True, 'https://example.invalid/item.png')
        assert item.composition_json == [{'name': 'Cotton', 'percentage': 0.0}, {'name': 'Wool', 'percentage': 25.0}]
        audit_row = db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').one()
        assert audit_row.user_id == actor_id
        assert audit_row.old_value_json == {'sku': old_sku, 'name': old_name, 'category': 'fabric', 'unit': 'm', 'is_active': True}
        assert audit_row.new_value_json == {'sku': values['sku'], 'name': 'Материал 🧵'}
    chain(sessions)


@pytest.mark.parametrize('point', ['enqueue', 'finalize', 'commit'])
def test_pg_update_audit_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    item_id, old_sku, old_name = make_item(sessions)
    values = item_values()
    original = stock_service.log_action
    def fail(*args, **kwargs):
        raise RuntimeError('injected audit failure')
    def wrapped(db, *args, **kwargs):
        result = original(db, *args, **kwargs)
        if point == 'enqueue':
            fail()
        if point == 'commit':
            event.listen(db, 'before_commit', fail)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(stock_service, 'log_action', wrapped)
        if point == 'finalize':
            patch.setattr(audit_service, '_audit_entry_hash', fail)
        with client_for(sessions) as client:
            assert client.patch(f'/inventory/items/{item_id}', headers=auth(actor_id), json=values).status_code == 500
    with sessions() as db:
        item = db.get(Item, item_id)
        assert (item.sku, item.name, item.unit, item.default_cost) == (old_sku, old_name, 'm', Decimal('2'))
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 0
    with client_for(sessions) as client:
        response = client.patch(f'/inventory/items/{item_id}', headers=auth(actor_id), json=values)
    assert response.status_code == 200, response.text
    with sessions() as db:
        assert db.get(Item, item_id).sku == values['sku']
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 1
    chain(sessions)


def test_pg_two_conflicting_sku_updates_preserve_unique_index(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.items'])
    ids = [make_item(sessions)[0] for _ in range(2)]
    sku = 'CONFLICT-' + uuid4().hex
    names = ['Race ' + uuid4().hex for _ in ids]
    barrier = Barrier(2)
    original = stock_service._item_payload
    def after_duplicate_check(payload):
        barrier.wait(timeout=10)
        return original(payload)
    monkeypatch.setattr(stock_service, '_item_payload', after_duplicate_check)
    with sessions() as db:
        indexes = inspect(db.connection()).get_indexes('items')
        uniques = {x['name'] for x in indexes if x.get('unique') and x.get('column_names') == ['sku']}
        assert 'ix_items_sku' in uniques
    def worker(index):
        with sessions() as db:
            try:
                stock_service.update_item(db, ids[index], ItemIn(sku=sku, name=names[index], category='fabric', unit='kg'), db.get(User, actor_id))
                return index, 'updated', None, None
            except IntegrityError as error:
                original_error = error.orig
                state = getattr(original_error, 'sqlstate', None) or getattr(original_error, 'pgcode', None)
                constraint = getattr(getattr(original_error, 'diag', None), 'constraint_name', None)
                db.rollback()
                return index, 'integrity_error', state, constraint
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(result[1] for result in results) == ['integrity_error', 'updated']
    loser = next(result for result in results if result[1] == 'integrity_error')
    winner = next(result for result in results if result[1] == 'updated')
    assert loser[2] == '23505' and loser[3] in uniques
    with sessions() as db:
        assert db.query(Item).filter_by(sku=sku).one().id == ids[winner[0]]
        assert db.get(Item, ids[loser[0]]).sku != sku
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=ids[loser[0]], action='update').count() == 0
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=ids[winner[0]], action='update').count() == 1
    chain(sessions)
