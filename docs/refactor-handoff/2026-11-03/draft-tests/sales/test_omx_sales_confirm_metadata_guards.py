"""Supplemental frozen Sales metadata/guard characterization; no PG or network."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.sales import router
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.models.sales import orders_service
from app.schemas import Customer, Model, SalesOrder, SalesOrderItem, User


SUMMARY_KEYS = {'id', 'order_no', 'customer_id', 'customer_name', 'customer', 'order_type', 'status',
    'deadline', 'total_amount', 'planning_estimated_material_cost', 'planning_estimated_labor_cost',
    'planning_estimated_electricity_cost', 'planning_estimated_other_cost', 'planning_estimated_net_cost',
    'planning_suggested_price_15', 'planning_suggested_price_20', 'planning_estimated_lead_time_minutes',
    'planning_estimate_comment', 'planning_estimate_submitted_at', 'planning_estimate_submitted_by',
    'printing_instructions', 'printing_attachments', 'notes', 'created_at'}
ITEM_KEYS = {'id', 'sales_order_id', 'model_id', 'model_code', 'model_name', 'brand_id', 'collection_id',
    'color', 'size', 'quantity', 'requested_pack_count', 'unit_price', 'printing_required', 'source_type',
    'notes', 'model'}


@pytest.fixture
def sales():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, autoflush=False, expire_on_commit=False)
    actor = User(name='Synthetic', email='metadata@example.invalid', password_hash='unused', extra_permissions=['*'])
    customer = Customer(name='Customer'); model = Model(code='METADATA', name='Model')
    db.add_all([actor, customer, model]); db.flush()
    order = SalesOrder(order_no='METADATA-ORDER', customer_id=customer.id, status='draft', order_type='client_order')
    db.add(order); db.flush()
    db.add(SalesOrderItem(sales_order_id=order.id, model_id=model.id, color='white', size='M', quantity=1,
                          unit_price=0, source_type='produce_new', printing_required=False))
    db.commit()
    app = FastAPI()
    def db_override():
        try: yield db
        finally: db.rollback()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: actor
    app.include_router(router, prefix='/api')
    with TestClient(app) as client: yield db, order, model, client
    db.close(); engine.dispose()


@pytest.mark.parametrize('details,translation,composition', [
    (None, None, None), ('scalar', None, None), (12, None, None), (['list'], None, None),
    ({}, None, None), ({'translation': None, 'composition': None}, None, None),
    ({'translation': {'en': 'Text'}, 'composition': {'fiber': ['cotton']}}, {'en': 'Text'}, {'fiber': ['cotton']}),
    ({'translation': 'bad', 'composition': 7}, 'bad', 7),
    ({'translation': ['bad'], 'composition': ['cotton']}, ['bad'], ['cotton']),
    ({'translation': 4, 'composition': 'cotton'}, 4, 'cotton'),
])
def test_direct_metadata_raw_and_http_validation(sales, details, translation, composition):
    db, order, model, client = sales
    model.details_json = details; db.commit()
    row = orders_service.get_sales_order(order.id, db)
    ref = row['items'][0]['model']
    assert ref == {'id': model.id, 'code': 'METADATA', 'name': 'Model', 'translations': translation, 'composition': composition}
    if translation is not None and not isinstance(translation, dict):
        with pytest.raises(ResponseValidationError) as exc:
            client.get(f'/api/sales-orders/{order.id}')
        assert any(e['type'] == 'dict_type' and tuple(e['loc'])[-1] == 'translations' for e in exc.value.errors())
    else:
        response = client.get(f'/api/sales-orders/{order.id}')
        assert response.status_code == 200
        assert response.json()['items'][0]['model'] == {'id': model.id, 'code': 'METADATA', 'name': 'Model', 'translations': translation}


def test_exact_direct_summary_and_detail_keys_nulls_enum_members(sales):
    db, order, model, client = sales
    summary = orders_service._serialize_sales_order(db, order)
    detail = orders_service.get_sales_order(order.id, db)
    assert set(summary) == SUMMARY_KEYS
    assert set(detail) == SUMMARY_KEYS | {'items'}
    assert summary['status'] is SalesOrderStatus.DRAFT and summary['order_type'] is SalesOrderType.CLIENT_ORDER
    assert summary['deadline'] is None and summary['notes'] is None and summary['printing_instructions'] is None
    assert summary['customer'] == {'id': order.customer_id, 'name': 'Customer'}
    item = detail['items'][0]
    assert set(item) == ITEM_KEYS and item['source_type'] is SalesOrderItemSourceType.PRODUCE_NEW
    assert item['brand_id'] is None and item['collection_id'] is None and item['requested_pack_count'] is None
    assert item['notes'] is None and set(item['model']) == {'id', 'code', 'name', 'translations', 'composition'}


@pytest.mark.parametrize('value', ['DRAFT', ' draft ', '', None, 123, ['draft'], {'x': 1}, b'draft'])
def test_direct_mocked_noncanonical_status_400_before_writer(value, monkeypatch):
    class DB:
        def get(self, _model, _id): return SimpleNamespace(status=value)
    def forbidden(*_args, **_kwargs): pytest.fail('non-draft reached writer')
    monkeypatch.setattr(orders_service, 'set_sales_order_status', forbidden)
    with pytest.raises(HTTPException) as exc:
        orders_service.confirm_sales_order(1, DB(), SimpleNamespace(id=1))
    assert exc.value.status_code == 400
    assert exc.value.detail == f"Cannot confirm order in status '{value}'"


def test_direct_mocked_missing_order_404_before_status_or_writer(monkeypatch):
    class DB:
        def get(self, _model, _id): return None
    monkeypatch.setattr(orders_service, 'set_sales_order_status', lambda *_: pytest.fail('writer reached'))
    with pytest.raises(HTTPException) as exc: orders_service.confirm_sales_order(99, DB(), SimpleNamespace(id=1))
    assert exc.value.status_code == 404 and exc.value.detail == 'Sales order not found'


def test_direct_mocked_status_stringification_typeerror_before_writer(monkeypatch):
    class BadString:
        def __str__(self): raise TypeError('synthetic status string failure')
    class DB:
        def get(self, _model, _id): return SimpleNamespace(status=BadString())
    monkeypatch.setattr(orders_service, 'set_sales_order_status', lambda *_: pytest.fail('writer reached'))
    with pytest.raises(TypeError, match='synthetic status string failure'):
        orders_service.confirm_sales_order(1, DB(), SimpleNamespace(id=1))
