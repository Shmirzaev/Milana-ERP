"""Frozen-source direct/HTTP Sales serialization characterization; SQLite only."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.sales import router
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.libs.dto.sales.sales_order_input import SalesOrderIn
from app.libs.dto.sales.sales_order_output import SalesOrderDetail, SalesOrderOut
from app.libs.dto.sales.sales_order_update import SalesOrderUpdate
from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.models.sales import orders_service
from app.schemas import AuditLog, Customer, Model, Notification, SalesOrder, SalesOrderItem, User


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, autoflush=False, expire_on_commit=False)
    actor = User(name='Synthetic sales', email='sales@example.invalid', password_hash='unused', extra_permissions=['*'])
    customer = Customer(name='Synthetic customer')
    model = Model(code='MODEL-CHAR', name='Synthetic garment', details_json={'translation': {'en': 'Garment'}, 'composition': 'cotton'})
    db.add_all([actor, customer, model]); db.flush()
    order = SalesOrder(order_no='CHAR-EXISTING', customer_id=customer.id, status='draft', order_type='client_order',
                       deadline=datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), total_amount=6,
                       printing_attachments=[{'file_url': '/private/image.png', 'file_name': 'p', 'content_type': None}])
    db.add(order); db.flush()
    db.add(SalesOrderItem(sales_order_id=order.id, model_id=model.id, color='white', size='M', quantity=2,
                          unit_price=3, source_type='produce_new', printing_required=False))
    db.commit()
    monkeypatch.setattr(orders_service, 'sign_path', lambda path: path + '?synthetic=1')
    app = FastAPI()
    def supplied_db():
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = supplied_db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        yield db, actor, customer, model, order, client
    db.close(); engine.dispose()


@pytest.mark.parametrize('operation', ['list', 'create', 'detail', 'update', 'confirm'])
@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_five_consumers_current_contract(setup, operation, surface):
    db, actor, customer, model, order, client = setup
    payload = {'customer_id': customer.id, 'deadline': '2030-01-02T03:04:05Z',
               'printing_attachments': [{'file_url': '/private/image.png', 'file_name': 'p'}],
               'items': [{'model_id': model.id, 'color': 'white', 'size': 'M', 'quantity': 2, 'unit_price': 3}]}
    if surface == 'direct':
        if operation == 'list': result = orders_service.list_sales_orders(db)[0]
        elif operation == 'create': result = orders_service.create_sales_order(SalesOrderIn(**payload), db, actor)
        elif operation == 'detail': result = orders_service.get_sales_order(order.id, db)
        elif operation == 'update': result = orders_service.update_sales_order(order.id, SalesOrderUpdate(notes='updated'), db, actor)
        else: result = orders_service.confirm_sales_order(order.id, db, actor)
        assert isinstance(result, SalesOrderDetail if operation == 'create' else SalesOrderOut) if operation in ('create', 'update') else type(result) is dict
        row = result.model_dump() if isinstance(result, (SalesOrderDetail, SalesOrderOut)) else result
        assert row['status'] is (SalesOrderStatus.CONFIRMED if operation == 'confirm' else SalesOrderStatus.DRAFT)
        assert row['order_type'] is SalesOrderType.CLIENT_ORDER
        assert isinstance(row['deadline'], datetime)
    else:
        if operation == 'list': response = client.get('/api/sales-orders'); row = response.json()[0]
        elif operation == 'create': response = client.post('/api/sales-orders', json=payload); row = response.json()
        elif operation == 'detail': response = client.get(f'/api/sales-orders/{order.id}'); row = response.json()
        elif operation == 'update': response = client.patch(f'/api/sales-orders/{order.id}', json={'notes': 'updated'}); row = response.json()
        else: response = client.post(f'/api/sales-orders/{order.id}/confirm'); row = response.json()
        assert response.status_code == (201 if operation == 'create' else 200), response.text
        assert row['status'] == ('confirmed' if operation == 'confirm' else 'draft')
        assert row['order_type'] == 'client_order'
        expected_deadlines = {
            'list': '2030-01-02T03:04:05+00:00',
            'create': '2030-01-02T03:04:05',
            'detail': '2030-01-02T03:04:05Z',
            'update': '2030-01-02T03:04:05',
            'confirm': '2030-01-02T03:04:05',
        }
        assert row['deadline'] == expected_deadlines[operation]
    assert row['customer'] == {'id': customer.id, 'name': 'Synthetic customer'}
    assert row['customer_name'] == 'Synthetic customer'
    assert row['printing_attachments'][0]['file_url'] == '/private/image.png?synthetic=1'
    if operation in ('create', 'detail'):
        item = row['items'][0]
        assert item['model']['id'] == model.id and item['model']['code'] == 'MODEL-CHAR'
        assert item['model']['translations'] == {'en': 'Garment'}
        assert item['source_type'] == (SalesOrderItemSourceType.PRODUCE_NEW if surface == 'direct' else 'produce_new')
        if operation == 'detail' and surface == 'direct': assert item['model']['composition'] == 'cotton'
        else: assert 'composition' not in item['model']


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_missing_customer_and_missing_model_projection(setup, surface):
    db, actor, customer, model, order, client = setup
    order.customer_id = None
    db.query(SalesOrderItem).filter_by(sales_order_id=order.id).delete(); db.commit()
    result = orders_service.get_sales_order(order.id, db) if surface == 'direct' else client.get(f'/api/sales-orders/{order.id}').json()
    assert result['customer'] is None and result['customer_name'] is None and result['items'] == []


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_confirm_signing_failure_occurs_after_commit(setup, monkeypatch, surface):
    db, actor, customer, model, order, client = setup
    engine, order_id = db.get_bind(), order.id
    def fail(_): raise RuntimeError('synthetic signer failure')
    monkeypatch.setattr(orders_service, 'sign_path', fail)
    with pytest.raises(RuntimeError, match='synthetic signer failure'):
        if surface == 'direct': orders_service.confirm_sales_order(order.id, db, actor)
        else: client.post(f'/api/sales-orders/{order.id}/confirm')
    db.close()
    with Session(engine) as fresh:
        assert fresh.get(SalesOrder, order_id).status == 'confirmed'
        assert fresh.query(AuditLog).filter_by(action='confirm', entity_id=order_id).count() == 1
        assert fresh.query(Notification).count() == 0


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_missing_model_reference_projection(setup, surface):
    db, actor, customer, model, order, client = setup
    # SQLite-only synthetic orphan: characterization of projection fallback,
    # not a claim that a foreign-key-enforced PostgreSQL database permits it.
    line = db.query(SalesOrderItem).filter_by(sales_order_id=order.id).one()
    line.model_id = 987654; db.commit()
    result = orders_service.get_sales_order(order.id, db) if surface == 'direct' else client.get(f'/api/sales-orders/{order.id}').json()
    assert result['items'][0]['model'] is None
    assert result['items'][0]['model_code'] is None and result['items'][0]['model_name'] is None


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_confirm_invalid_output_type_validation_occurs_after_commit(setup, surface):
    db, actor, customer, model, order, client = setup
    engine, order_id = db.get_bind(), order.id
    # order_type has no mapped CHECK; invalid legacy value is a synthetic witness.
    order.order_type = 'legacy_unknown'; db.commit()
    with pytest.raises(ValidationError) as caught:
        if surface == 'direct': orders_service.confirm_sales_order(order.id, db, actor)
        else: client.post(f'/api/sales-orders/{order.id}/confirm')
    assert 'order_type' in str(caught.value)
    db.close()
    with Session(engine) as fresh:
        assert fresh.get(SalesOrder, order_id).status == 'confirmed'
        assert fresh.query(AuditLog).filter_by(action='confirm', entity_id=order_id).count() == 1
        assert fresh.query(Notification).count() == 0
