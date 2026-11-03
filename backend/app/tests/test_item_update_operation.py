from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event

from app.libs.dto.inventory.item_input import ItemIn
from app.models.inventory import stock_service as service
from app.schemas import AuditLog, Item, User
from app.tests.conftest import TestSessionLocal


def payload(**overrides):
    return ItemIn(**({'sku': 'UPD-NEW', 'name': '  Материал 🧵  ', 'category': 'fabric', 'unit': 'kg'} | overrides))


@pytest.fixture
def db():
    with TestSessionLocal() as session:
        item = Item(sku='UPD-OLD', name='Before', category='fabric', unit='m', default_cost=2, reorder_level=3, track_batch=True, is_active=True, image_url='https://old', composition_json=[{'name': 'Old', 'percentage': 100}])
        session.add(item)
        session.commit()
        yield session, item.id


def assert_original_item_and_no_update_audit(session, item_id):
    session.expire_all()
    item = session.get(Item, item_id)
    assert (item.sku, item.name, item.category, item.unit) == ('UPD-OLD', 'Before', 'fabric', 'm')
    assert (item.default_cost, item.reorder_level, item.track_batch, item.is_active) == (Decimal('2'), Decimal('3'), True, True)
    assert item.image_url == 'https://old'
    assert item.composition_json == [{'name': 'Old', 'percentage': 100}]
    assert session.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 0


def test_update_persists_full_payload_and_audit_and_attribute_events(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    seen = []
    def on_set(target, value, oldvalue, initiator):
        if target.id == item_id:
            seen.append((initiator.key, value))
    event.listen(Item.name, 'set', on_set)
    try:
        result = service.update_item(session, item_id, payload(default_cost='1.23455', reorder_level='4.2500', image_url='  https://example.test/🧵  ', composition=[{'name': '  Хлопок  ', 'percentage': 50}, {'name': '  ', 'percentage': 20}, {'name': 'É', 'percentage': 50}], track_batch=True), None)
    finally:
        event.remove(Item.name, 'set', on_set)
    assert result.id == item_id
    assert ('name', 'Материал 🧵') in seen
    session.expire_all()
    saved = session.get(Item, item_id)
    assert (saved.sku, saved.name, saved.category, saved.unit) == ('UPD-NEW', 'Материал 🧵', 'fabric', 'kg')
    assert saved.default_cost == Decimal('1.2346') and saved.reorder_level == Decimal('4.2500')
    assert saved.track_batch is True and saved.is_active is True
    assert saved.image_url == 'https://example.test/🧵'
    assert saved.composition_json == [{'name': 'Хлопок', 'percentage': 50.0}, {'name': 'É', 'percentage': 50.0}]
    audit = session.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').one()
    assert audit.old_value_json == {'sku': 'UPD-OLD', 'name': 'Before', 'category': 'fabric', 'unit': 'm', 'is_active': True}
    assert audit.new_value_json == {'sku': 'UPD-NEW', 'name': 'Материал 🧵'}


def test_omitted_fields_are_replaced_by_defaults_not_patch_semantics(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    service.update_item(session, item_id, payload(image_url=None), None)
    session.expire_all()
    saved = session.get(Item, item_id)
    assert (saved.default_cost, saved.reorder_level, saved.track_batch, saved.is_active, saved.image_url, saved.composition_json) == (Decimal('0'), Decimal('0'), False, True, None, [])


@pytest.mark.parametrize('kwargs, message', [
    ({'image_url': '  JaVaScRiPt:alert(1)'}, 'Unsupported image URL'),
    ({'image_url': '/other'}, 'Image URL must be an uploaded file path or an http(s) URL'),
    ({'composition': [{'name': 'a', 'percentage': 60}, {'name': 'b', 'percentage': 41}]}, 'Composition total cannot exceed 100%'),
    ({'name': ' \u2003 '}, 'Item name is required'),
])
def test_normalization_refusals(db, monkeypatch, kwargs, message):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, item_id, payload(**kwargs), None)
    assert (exc.value.status_code, exc.value.detail) == (400, message)
    assert_original_item_and_no_update_audit(session, item_id)


def test_duplicate_sku_precedes_invalid_image(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    session.add(Item(sku='DUP', name='Other', category='fabric', unit='kg'))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, item_id, payload(sku='DUP', image_url='javascript:x'), None)
    assert exc.value.detail == 'SKU already exists'
    assert_original_item_and_no_update_audit(session, item_id)


def test_audit_failure_requires_caller_rollback_and_is_atomic(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    def fail_audit(supplied_session, *args, **kwargs):
        assert supplied_session is session
        supplied_session.flush()
        raise RuntimeError('audit failure')
    monkeypatch.setattr(service, 'log_action', fail_audit)
    with pytest.raises(RuntimeError, match='audit failure'):
        service.update_item(session, item_id, payload(), None)
    session.rollback()
    assert session.get(Item, item_id).name == 'Before'
    assert session.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 0


@pytest.mark.parametrize('field,value', [('default_cost', None), ('reorder_level', None), ('composition', None), ('default_cost', '-1'), ('reorder_level', '10000000000'), ('composition', [{'name': 'x', 'percentage': 101}])])
def test_dto_rejects_nulls_and_out_of_bounds(field, value):
    with pytest.raises(ValidationError):
        payload(**{field: value})


def test_permission_precedence_existing_item_then_requested_category_then_not_found(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'user_permissions', lambda user: {'inventory.materials_only'})
    session.get(Item, item_id).category = 'accessory'
    session.commit()
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, item_id, payload(category='accessory'), object())
    assert (exc.value.status_code, exc.value.detail) == (403, 'Only material inventory is available to this user')
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, 999999, payload(category='accessory'), object())
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, 999999, payload(category='fabric'), object())
    assert (exc.value.status_code, exc.value.detail) == (404, 'Item not found')


def test_active_name_group_conflict_and_inactive_bypass(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    session.add(Item(sku='OTHER', name='  Cotton  ', category='semi_finished', unit='kg', is_active=True))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        service.update_item(session, item_id, payload(name=' cotton '), None)
    assert (exc.value.status_code, exc.value.detail) == (400, 'Material name already exists')
    assert_original_item_and_no_update_audit(session, item_id)
    service.update_item(session, item_id, payload(name=' cotton ', is_active=False), None)
    assert session.get(Item, item_id).name == 'cotton'


def test_commit_failure_rolls_back_both_item_and_audit(db, monkeypatch):
    session, item_id = db
    monkeypatch.setattr(service.inventory_access, 'require_item', lambda *args: None)
    monkeypatch.setattr(service.inventory_access, 'require_category', lambda *args: None)
    def fail_commit():
        raise RuntimeError('commit failed')
    monkeypatch.setattr(session, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='commit failed'):
        service.update_item(session, item_id, payload(), None)
    session.rollback()
    assert session.get(Item, item_id).name == 'Before'
    assert session.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 0


def test_real_audit_append_failure_rolls_back_item_and_audit(db, monkeypatch):
    session, item_id = db
    original_log = service.log_action
    def append_then_fail(supplied_session, *args, **kwargs):
        assert supplied_session is session
        original_log(supplied_session, *args, **kwargs)
        assert supplied_session.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 1
        raise RuntimeError('after audit append')
    monkeypatch.setattr(service, 'log_action', append_then_fail)
    with pytest.raises(RuntimeError, match='after audit append'):
        service.update_item(session, item_id, payload(), session.query(User).filter_by(email='admin@example.com').one())
    session.rollback()
    with TestSessionLocal() as check:
        assert check.get(Item, item_id).name == 'Before'
        assert check.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='update').count() == 0


def test_http_authorization_scope_and_actor_audit(client):
    from app.core.security import create_access_token
    from app.schemas import User
    with TestSessionLocal() as session:
        allowed = User(name='Item scoped', email='item-scoped@example.com', password_hash='unused', extra_permissions=['storage.items', 'inventory.materials_only'])
        denied = User(name='Item denied', email='item-denied@example.com', password_hash='unused', extra_permissions=[])
        material = Item(sku='HTTP-MAT', name='Material original', category='fabric', unit='kg')
        accessory = Item(sku='HTTP-ACC', name='Accessory original', category='accessory', unit='pcs')
        session.add_all([allowed, denied, material, accessory])
        session.commit()
        allowed_id, denied_id, material_id, accessory_id = allowed.id, denied.id, material.id, accessory.id
    headers = lambda user_id: {'Authorization': f'Bearer {create_access_token(str(user_id))}'}
    body = {'sku': 'HTTP-MAT-UPDATED', 'name': 'Material updated', 'category': 'fabric', 'unit': 'kg'}
    denied_response = client.patch(f'/api/inventory/items/{material_id}', headers=headers(denied_id), json=body)
    assert denied_response.status_code == 403, denied_response.text
    scope_response = client.patch(f'/api/inventory/items/{accessory_id}', headers=headers(allowed_id), json=body)
    assert scope_response.status_code == 403, scope_response.text
    with TestSessionLocal() as check:
        assert check.get(Item, material_id).name == 'Material original'
        assert check.get(Item, accessory_id).name == 'Accessory original'
        assert check.query(AuditLog).filter(AuditLog.entity_type == 'Item', AuditLog.entity_id.in_([material_id, accessory_id]), AuditLog.action == 'update').count() == 0
    ok = client.patch(f'/api/inventory/items/{material_id}', headers=headers(allowed_id), json=body)
    assert ok.status_code == 200, ok.text
    with TestSessionLocal() as check:
        assert check.get(Item, material_id).name == 'Material updated'
        audit = check.query(AuditLog).filter_by(entity_type='Item', entity_id=material_id, action='update').one()
        assert audit.user_id == allowed_id
        assert audit.old_value_json['name'] == 'Material original'
        assert audit.new_value_json == {'sku': 'HTTP-MAT-UPDATED', 'name': 'Material updated'}
