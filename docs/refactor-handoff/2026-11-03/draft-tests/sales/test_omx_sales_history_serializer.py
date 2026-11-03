"""Read-only history's nested Sales serializer: frozen-source characterization."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.sales import router
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.models.sales import history_service, orders_service
from app.schemas import AuditLog, Customer, Model, Notification, SalesOrder, SalesOrderItem, User


@pytest.fixture
def history(monkeypatch):
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, autoflush=False, expire_on_commit=False)
    actor = User(name='Synthetic', email='history@example.invalid', password_hash='unused', extra_permissions=['*'])
    customer = Customer(name='History customer')
    model = Model(code='HISTORY-MODEL', name='History garment', details_json={'translation': {'en': 'Garment'}, 'composition': ['cotton']})
    db.add_all([actor, customer, model]); db.flush()
    order = SalesOrder(order_no='HISTORY-ORDER', customer_id=customer.id, status='draft', order_type='client_order',
                       deadline=datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), total_amount=6,
                       printing_attachments=[{'file_url': '/private/history.png', 'file_name': 'h', 'content_type': None}])
    db.add(order); db.flush()
    db.add(SalesOrderItem(sales_order_id=order.id, model_id=model.id, color='white', size='M', quantity=2,
                          unit_price=3, source_type='produce_new', printing_required=False)); db.commit()
    monkeypatch.setattr(orders_service, 'sign_path', lambda path: path + '?synthetic=1')
    app = FastAPI()
    def db_override():
        try: yield db
        finally: db.rollback()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: actor
    app.include_router(router, prefix='/api')
    with TestClient(app) as client: yield db, order, model, customer, client
    db.close(); engine.dispose()


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_history_nested_order_keeps_enrichment_and_empty_adjacent_graph(history, surface):
    db, order, model, customer, client = history
    if surface == 'direct':
        result = history_service.get_sales_order_history(order.id, db)
        assert result['order']['status'] is SalesOrderStatus.DRAFT
        assert result['order']['order_type'] is SalesOrderType.CLIENT_ORDER
        assert result['order']['items'][0]['source_type'] is SalesOrderItemSourceType.PRODUCE_NEW
        assert isinstance(result['order']['deadline'], datetime)
    else:
        response = client.get(f'/api/sales-orders/{order.id}/history')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['order']['status'] == 'draft' and result['order']['order_type'] == 'client_order'
        assert result['order']['deadline'] == '2030-01-02T03:04:05+00:00'
        assert result['order']['items'][0]['source_type'] == 'produce_new'
    assert result['record_type'] == 'sales_order' and result['order_no'] == 'HISTORY-ORDER'
    assert result['order']['customer'] == {'id': customer.id, 'name': 'History customer'}
    assert result['order']['printing_attachments'][0]['file_url'] == '/private/history.png?synthetic=1'
    assert result['order']['items'][0]['model'] == {'id': model.id, 'code': 'HISTORY-MODEL', 'name': 'History garment',
                                                    'translations': {'en': 'Garment'}, 'composition': ['cotton']}
    assert result['items'][0]['quantity'] == 2 and result['items'][0]['line_total'] == 6
    assert result['summary']['ordered_qty'] == 2 and result['summary']['order_amount'] == 6
    for key in ('production_orders', 'invoices', 'payments', 'shipments'):
        assert result[key] == []
    assert db.query(SalesOrder).count() == 1 and db.query(SalesOrderItem).count() == 1
    assert db.query(AuditLog).count() == 0 and db.query(Notification).count() == 0


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_history_missing_order_is_404(history, surface):
    db, order, model, customer, client = history
    if surface == 'direct':
        with pytest.raises(HTTPException) as exc: history_service.get_sales_order_history(9999, db)
        assert exc.value.status_code == 404 and exc.value.detail == 'Sales order not found'
    else:
        response = client.get('/api/sales-orders/9999/history')
        assert response.status_code == 404 and response.json() == {'detail': 'Sales order not found'}
