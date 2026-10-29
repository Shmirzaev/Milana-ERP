"""Used service results keep their typed contract before FastAPI serialization."""
from typing import get_type_hints
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from app.api.routes import sales as routes
from app.db.session import SessionLocal
from app.libs.dto.sales.sales_order_output import SalesOrderDetail
from app.libs.dto.sales.sales_stock_output import SalesStockReservationOut
from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.models.sales import orders_service
from app.schemas import Customer, IdempotencyRecord, Model, SalesOrder, SalesOrderItem, StockReservation
from app.tests.test_sales_order_create_contract import _model_id, _line
from app.tests.test_sales_ready_packs import _packs


def test_used_create_and_reserve_return_annotations_are_concrete_dtos():
    assert get_type_hints(orders_service.create_sales_order)['return'] is SalesOrderDetail
    assert get_type_hints(routes.create_sales_order)['return'] is SalesOrderDetail
    assert get_type_hints(orders_service.reserve_stock)['return'] is SalesStockReservationOut
    assert get_type_hints(routes.reserve_stock)['return'] is SalesStockReservationOut


def test_create_returns_enum_members_and_preserves_signed_nested_http_shape(client, auth_headers, monkeypatch):
    model_id = _model_id(client, auth_headers)
    with SessionLocal() as db:
        customer = Customer(name='Typed result customer')
        db.add(customer)
        model = db.get(Model, model_id)
        model.details_json = {'translation': {'en': 'Translated garment'}, 'composition': 'Cotton'}
        db.commit()
        customer_id, code, name = customer.id, model.code, model.name
    results = []
    original = orders_service.create_sales_order
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        results.append(result)
        return result
    monkeypatch.setattr(orders_service, 'create_sales_order', capture)
    path = '/storage/sales-order-files/typed-result.png'
    response = client.post('/api/sales-orders', headers=auth_headers, json={
        'customer_id': customer_id, 'items': [_line(model_id)],
        'printing_attachments': [{'file_url': path, 'file_name': 'Print reference'}],
    })
    assert response.status_code == 201, response.text
    result, = results
    assert type(result) is SalesOrderDetail
    assert result.order_type is SalesOrderType.CLIENT_ORDER
    assert result.status is SalesOrderStatus.DRAFT
    assert result.items[0].source_type is SalesOrderItemSourceType.PRODUCE_NEW
    assert result.items[0].model.translations == {'en': 'Translated garment'}
    body = response.json()
    assert body == result.model_dump(mode='json')
    assert body['customer'] == {'id': customer_id, 'name': 'Typed result customer'}
    assert body['customer_name'] == 'Typed result customer'
    assert body['items'][0]['model'] == {'id': model_id, 'code': code, 'name': name,
                                        'translations': {'en': 'Translated garment'}}
    signed = body['printing_attachments'][0]['file_url']
    assert urlsplit(signed).path == path
    assert parse_qs(urlsplit(signed).query)
    with SessionLocal() as db:
        assert db.get(SalesOrder, body['id']).printing_attachments[0]['file_url'] == path


def test_reserve_live_and_saved_replay_return_same_typed_result_and_json(client, auth_headers, monkeypatch):
    model_id, _ = _packs((6,))
    with SessionLocal() as db:
        order = SalesOrder(order_no='TYPED-'+uuid4().hex[:12], order_type='branded_stock_sale', status='draft')
        db.add(order)
        db.flush()
        db.add(SalesOrderItem(sales_order_id=order.id, model_id=model_id, color='mixed', size='any',
                              quantity=0, requested_pack_count=1, source_type='from_stock', unit_price=2))
        db.commit()
        order_id = order.id
    results = []
    original = orders_service.reserve_stock
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        results.append(result)
        return result
    monkeypatch.setattr(orders_service, 'reserve_stock', capture)
    headers = {**auth_headers, 'Idempotency-Key': 'typed-'+uuid4().hex}
    first = client.post(f'/api/sales-orders/{order_id}/reserve-stock', headers=headers)
    replay = client.post(f'/api/sales-orders/{order_id}/reserve-stock', headers=headers)
    assert first.status_code == replay.status_code == 200, (first.text, replay.text)
    assert first.json() == replay.json()
    assert len(results) == 2
    for result in results:
        assert type(result) is SalesStockReservationOut
        assert result.model_dump(mode='json') == first.json()
        assert sum(row.qty for row in result.reservations) == 6
        assert result.shortages == []
    with SessionLocal() as db:
        assert db.query(StockReservation).filter_by(sales_order_id=order_id).count() == 2
        saved = db.query(IdempotencyRecord).filter_by(key=headers['Idempotency-Key']).one()
        assert saved.response_json == first.json()


def test_stock_result_preserves_legacy_display_none_and_shortage_fields():
    wire = {'reservations': [{'stock_id': 11, 'package_id': None, 'qty': 2}],
            'shortages': [{'model_id': 4, 'brand_id': None, 'color': 'white', 'size': 'M', 'shortage': 3}]}
    result = SalesStockReservationOut.model_validate(wire)
    assert result.reservations[0].package_id is None
    assert result.shortages[0].shortage == 3
    assert result.model_dump(mode='json') == wire
