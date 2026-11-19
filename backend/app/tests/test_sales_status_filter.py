from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from app.api.routes import sales
from app.core.deps import get_current_user
from app.db.session import get_db
from app.libs.dto.sales.sales_order_filter import SalesStatusFilter
from app.libs.enums.sales import SalesOrderStatus


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(sales.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: object()
    calls = []
    monkeypatch.setattr(sales.orders_service, 'list_sales_orders',
                        lambda db, **kwargs: calls.append(kwargs) or [])
    with TestClient(app) as client:
        yield client, calls


def test_status_filter_contract():
    adapter = TypeAdapter(SalesStatusFilter)
    assert adapter.validate_python('') is None
    assert adapter.validate_python(None) is None
    for status in SalesOrderStatus:
        assert adapter.validate_python(status.value) is status
        assert adapter.dump_python(status, mode='json') == status.value
    for invalid in ('unknown', ' CONFIRMED ', 'CONFIRMED', 'draft\u200b'):
        with pytest.raises(ValueError):
            adapter.validate_python(invalid)


def test_list_query_validates_and_forwards_to_service(client):
    http, calls = client
    for suffix, expected in (('', None), ('?status=', None),
                             ('?status=confirmed', SalesOrderStatus.CONFIRMED)):
        assert http.get('/sales-orders' + suffix).status_code == 200
        assert calls[-1]['status'] is expected
    count = len(calls)
    for value in ('unknown', 'CONFIRMED', 'draft%20'):
        assert http.get('/sales-orders?status=' + value).status_code == 422
    assert len(calls) == count
    schema = http.get('/openapi.json').json()
    parameter = next(p for p in schema['paths']['/sales-orders']['get']['parameters'] if p['name'] == 'status')
    assert any(item.get('$ref', '').endswith('/SalesOrderStatus') for item in parameter['schema']['anyOf'])


def test_http_status_filters_real_sales_query():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.schemas import SalesOrder

    engine = create_engine(
        'sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            SalesOrder(order_no='FILTER-DRAFT', status='draft', total_amount=0),
            SalesOrder(order_no='FILTER-CONFIRMED', status='confirmed', total_amount=0),
        ])
        session.commit()

    app = FastAPI()
    app.include_router(sales.router)

    def db_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_session
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        with TestClient(app) as http:
            for suffix in ('', '?status='):
                response = http.get('/sales-orders' + suffix)
                assert response.status_code == 200
                assert {row['order_no'] for row in response.json()} == {
                    'FILTER-DRAFT', 'FILTER-CONFIRMED'
                }
            response = http.get('/sales-orders?status=confirmed')
            assert response.status_code == 200
            assert [(row['order_no'], row['status']) for row in response.json()] == [
                ('FILTER-CONFIRMED', 'confirmed')
            ]
            assert http.get('/sales-orders?status=unknown').status_code == 422
    finally:
        engine.dispose()
