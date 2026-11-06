"""Item delete behavior through the existing HTTP service and supplied session."""
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models.inventory import stock_service
from app.schemas import (
    AuditLog, Item, Model, ModelBOM, PurchaseOrder, PurchaseOrderLine,
    PurchaseRequest, PurchaseRequestLine, Role, StockBatch, StockMovement,
    User, Warehouse, WasteRecord,
)
from app.tests.conftest import TestSessionLocal


def _actor(permissions):
    marker = uuid4().hex
    with TestSessionLocal.begin() as db:
        role = Role(name=f'item-delete-{marker}', permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name='Item delete actor', email=f'{marker}@example.invalid', password_hash='unused', role_id=role.id, is_active=True)
        db.add(user)
        db.flush()
        return {'Authorization': f'Bearer {create_access_token(user.id)}'}


def _item(link=None):
    marker = uuid4().hex
    with TestSessionLocal.begin() as db:
        item = Item(sku=f'DEL-{marker}', name=f'Delete {marker}', category='fabric', unit='kg', is_active=True)
        db.add(item)
        db.flush()
        if link == 'batch':
            warehouse = Warehouse(name=f'warehouse-{marker}', type='fabric_storage')
            db.add(warehouse)
            db.flush()
            db.add(StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=marker, quantity=1, unit='kg'))
        elif link == 'movement':
            db.add(StockMovement(item_id=item.id, movement_type='receive', quantity=1, unit='kg'))
        elif link == 'bom':
            model = Model(code=f'M-{marker}', name='Model')
            db.add(model)
            db.flush()
            db.add(ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=1, unit='kg'))
        elif link == 'request':
            request = PurchaseRequest(request_no=f'REQ-{marker}')
            db.add(request)
            db.flush()
            db.add(PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit='kg'))
        elif link == 'order':
            order = PurchaseOrder(po_no=f'PO-{marker}')
            db.add(order)
            db.flush()
            db.add(PurchaseOrderLine(purchase_order_id=order.id, item_id=item.id, unit='kg'))
        elif link == 'waste':
            db.add(WasteRecord(item_id=item.id, waste_type='test', quantity=1, unit='kg'))
        return item.id


@pytest.mark.parametrize('link', ['batch', 'movement', 'bom', 'request', 'order', 'waste'])
def test_all_existing_link_types_refuse_then_force_archive(client, auth_headers, link):
    item_id = _item(link)
    response = client.delete(f'/api/inventory/items/{item_id}', headers=auth_headers)
    assert response.status_code == 409
    response = client.delete(f'/api/inventory/items/{item_id}?force=true', headers=auth_headers)
    assert response.status_code == 204
    with TestSessionLocal() as db:
        assert db.get(Item, item_id).is_active is False
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='force_archive').count() == 1


def test_unlinked_hard_delete_and_force_permission_precedence(client, auth_headers):
    item_id = _item()
    linked_id = _item('waste')
    plain = _actor(['storage.items'])
    override = _actor(['storage.items', 'inventory.force_override'])
    assert client.delete(f'/api/inventory/items/{item_id + 1000000}?force=true', headers=plain).status_code == 403
    assert client.delete(f'/api/inventory/items/{item_id + 1000000}?force=true', headers=override).status_code == 404
    assert client.delete(f'/api/inventory/items/{linked_id}?force=true', headers=plain).status_code == 403
    assert client.delete(f'/api/inventory/items/{linked_id}?force=true', headers=override).status_code == 204
    assert client.delete(f'/api/inventory/items/{item_id}', headers=auth_headers).status_code == 204
    with TestSessionLocal() as db:
        assert db.get(Item, item_id) is None
        assert db.get(Item, linked_id).is_active is False
        assert db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id, action='delete').count() == 1


@pytest.mark.parametrize('link,force', [(None, False), ('waste', True)])
def test_audit_failure_rolls_back_item_delete_or_archive(client, auth_headers, monkeypatch, link, force):
    item_id = _item(link)
    original = stock_service.log_action

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected item audit failure')

    monkeypatch.setattr(stock_service, 'log_action', fail_after_audit)
    with pytest.raises(RuntimeError, match='injected item audit failure'):
        client.delete(f'/api/inventory/items/{item_id}?force={str(force).lower()}', headers=auth_headers)
    with TestSessionLocal() as db:
        assert db.get(Item, item_id).is_active is True
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'Item', AuditLog.entity_id == item_id, AuditLog.action.in_(['delete', 'force_archive'])).count() == 0
