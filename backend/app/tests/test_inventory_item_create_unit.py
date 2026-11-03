"""Item-create seam tests with fake sessions; no database or application startup."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.libs.dto.inventory.item_input import ItemIn
from app.libs.types.inventory import ItemInsertCommand
from app.models.inventory import stock_service as service
from app.schemas import Item
from app.schemas.inventory.item_persistence import insert_item


class FakeQuery:
    def __init__(self, db, entity):
        self.db, self.entity = db, entity

    def filter(self, *conditions):
        self.db.filters.append((self.entity, conditions))
        return self

    def first(self):
        return self.db.sku_match if self.entity is Item else self.db.name_match


class FakeSession:
    def __init__(self, *, sku_match=None, name_match=None):
        self.sku_match, self.name_match = sku_match, name_match
        self.events, self.filters, self.item = [], [], None

    def query(self, entity):
        self.events.append('sku_query' if entity is Item else 'name_query')
        return FakeQuery(self, entity)

    def add(self, item):
        self.events.append('add')
        self.item = item

    def flush(self):
        self.events.append('flush')
        self.item.id = 123

    def commit(self):
        self.events.append('commit')

    def refresh(self, item):
        assert item is self.item
        self.events.append('refresh')


def payload(**kw):
    return ItemIn(**({'sku': ' RAW-SKU ', 'name': '  Linen  ', 'category': 'fabric',
                      'unit': 'kg', 'default_cost': '1.23455', 'reorder_level': '2.34567'} | kw))


def prepare(monkeypatch, *, permissions=()):
    monkeypatch.setattr(service.inventory_access, 'user_permissions', lambda user: set(permissions))
    def audit(db, actor, action, entity, row_id, **kwargs):
        assert (action, entity, row_id, kwargs['new_value']) == ('create', 'Item', 123, {'sku': ' RAW-SKU '})
        db.events.append('audit')
    monkeypatch.setattr(service, 'log_action', audit)
    return SimpleNamespace()


def test_writer_adds_and_flushes_supplied_session_without_commit():
    db = FakeSession()
    command = ItemInsertCommand(sku='s', name='n', category='legacy free', unit='custom',
                                default_cost=Decimal('1.2345'), reorder_level=Decimal('2.34567'),
                                track_batch=True, is_active=False, image_url=None,
                                composition_json=[{'name': 'Cotton', 'percentage': 0.0}])
    row = insert_item(db, command)
    assert row is db.item
    assert db.events == ['add', 'flush']
    assert (row.sku, row.category, row.unit, row.default_cost, row.reorder_level) == (
        's', 'legacy free', 'custom', Decimal('1.2345'), Decimal('2.34567'))
    assert row.composition_json == [{'name': 'Cotton', 'percentage': 0.0}]


def test_create_preserves_normalization_audit_and_commit_order(monkeypatch):
    user = prepare(monkeypatch)
    db = FakeSession()
    captured = []
    original = service.item_persistence.insert_item
    def writer(session, command):
        captured.append((session, command))
        return original(session, command)
    monkeypatch.setattr(service.item_persistence, 'insert_item', writer)
    result = service.create_item(db, payload(image_url='  https://example.invalid/image.png  ',
        composition=[{'name':'  Cotton  ','percentage':0}, {'name':'  ','percentage':2},
                     {'name':'Wool','percentage':25}]), user)
    assert db.events == ['sku_query', 'name_query', 'add', 'flush', 'audit', 'commit', 'refresh']
    assert captured[0][0] is db and isinstance(captured[0][1], ItemInsertCommand)
    assert (result.sku, result.name, result.default_cost, result.reorder_level) == (
        ' RAW-SKU ', 'Linen', Decimal('1.2346'), Decimal('2.34567'))
    assert result.image_url == 'https://example.invalid/image.png'
    assert result.composition_json == [{'name':'Cotton','percentage':0.0}, {'name':'Wool','percentage':25.0}]
    sku_condition = db.filters[0][1][0]
    assert ' RAW-SKU ' in sku_condition.compile().params.values()


def test_authorization_then_raw_duplicate_precede_normalization(monkeypatch):
    user = prepare(monkeypatch, permissions=('inventory.materials_only',))
    db = FakeSession(sku_match=object())
    with pytest.raises(HTTPException) as caught:
        service.create_item(db, payload(category='accessory', image_url='javascript:bad'), user)
    assert (caught.value.status_code, caught.value.detail, db.events) == (
        403, 'Only material inventory is available to this user', [])
    user = prepare(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        service.create_item(db, payload(image_url='javascript:bad'), user)
    assert (caught.value.status_code, caught.value.detail, db.events) == (400, 'SKU already exists', ['sku_query'])


def test_active_name_group_and_inactive_blank_behavior(monkeypatch):
    user = prepare(monkeypatch)
    db = FakeSession(name_match=object())
    with pytest.raises(HTTPException) as caught:
        service.create_item(db, payload(category='semi_finished'), user)
    assert caught.value.detail == 'Material name already exists'
    params = [value for condition in db.filters[-1][1] for value in condition.compile().params.values()]
    assert ('fabric', 'semi_finished') in [tuple(x) for x in params if isinstance(x, (list, tuple))]
    inactive = FakeSession()
    result = service.create_item(inactive, payload(name='  ', is_active=False, category='legacy value', unit='custom'), user)
    assert result.name == '' and result.category == 'legacy value' and result.unit == 'custom'
    assert 'name_query' not in inactive.events


@pytest.mark.parametrize('url,expected', [('',None),('  ',None),(' /storage/model-files/a.png ', '/storage/model-files/a.png'),('http://example.invalid/a','http://example.invalid/a')])
def test_shared_payload_valid_image_rules(url, expected):
    assert service._item_payload(payload(image_url=url))['image_url'] == expected


@pytest.mark.parametrize('url', ['JavaScript:alert(1)', 'data:image/png;base64,a', 'HTTPS://example.invalid/a', '/other/a'])
def test_shared_payload_rejects_image_rules(url):
    with pytest.raises(HTTPException) as caught:
        service._item_payload(payload(image_url=url))
    assert caught.value.status_code == 400


def test_composition_threshold_and_empty_names():
    data = service._item_payload(payload(composition=[{'name':' ','percentage':99},{'name':'A','percentage':100}, {'name':'B','percentage':0.0001}]))
    assert data['composition_json'] == [{'name':'A','percentage':100.0},{'name':'B','percentage':0.0001}]
    with pytest.raises(HTTPException, match='Composition total cannot exceed'):
        service._item_payload(payload(composition=[{'name':'A','percentage':100},{'name':'B','percentage':0.0002}]))


def test_audit_failure_does_not_commit_or_refresh(monkeypatch):
    user = prepare(monkeypatch)
    db = FakeSession()
    def fail(*args, **kwargs):
        raise RuntimeError('audit failed')
    monkeypatch.setattr(service, 'log_action', fail)
    with pytest.raises(RuntimeError, match='audit failed'):
        service.create_item(db, payload(), user)
    assert db.events == ['sku_query', 'name_query', 'add', 'flush']


def test_active_blank_and_dto_refusal_remain_distinct(monkeypatch):
    user = prepare(monkeypatch)
    db = FakeSession()
    with pytest.raises(HTTPException) as caught:
        service.create_item(db, payload(name='  '), user)
    assert (caught.value.status_code, caught.value.detail) == (400, 'Item name is required')
    assert db.events == ['sku_query']
    with pytest.raises(ValidationError):
        payload(composition=[{'name': 'A', 'percentage': 101}])


def test_maximum_cost_rounding_remains_bounded():
    assert service._item_payload(payload(default_cost='99999999.99994'))['default_cost'] == Decimal('99999999.9999')
    with pytest.raises(ValidationError):
        payload(default_cost='99999999.99995')
