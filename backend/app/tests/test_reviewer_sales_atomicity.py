"""Late participant failures must roll back the complete sales creation operation."""
import pytest

from app.db.session import SessionLocal
from app.models.sales import orders_service, ready_stock_service
from app.schemas import AuditLog, FinishedGoodsStock, Notification, StockReservation
from app.tests.test_sales_branded_stock import _find_brand_id, _find_model_id, _insert_finished_goods_stock
from app.tests.test_sales_order_create_contract import _counts


def stock_state(stock_id):
    with SessionLocal() as db:
        row = db.get(FinishedGoodsStock, stock_id)
        return (int(row.available_qty), int(row.reserved_qty), row.status)


@pytest.mark.parametrize('participant', ['notification', 'audit'])
def test_late_failure_rolls_back_order_lines_stock_reservation_and_side_effects(client, auth_headers, monkeypatch, participant):
    model_id = _find_model_id(client, auth_headers, 'T-SHIRT-001')
    brand_id = _find_brand_id(client, auth_headers, 'Urban Co.')
    stock_id = _insert_finished_goods_stock(model_id=model_id, brand_id=brand_id,
                                           color='white', size='46', available_qty=30)
    before = _counts()
    prior_stock = stock_state(stock_id)
    module, name = ((ready_stock_service, 'notify_department') if participant == 'notification'
                    else (orders_service, 'log_action'))
    original = getattr(module, name)
    reached = []

    def fail_after_real_write(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.flush()
        row = db.get(FinishedGoodsStock, stock_id)
        assert (int(row.available_qty), int(row.reserved_qty)) == (18, 12)
        assert db.query(StockReservation).count() == before['stock_reservations'] + 1
        if participant == 'notification':
            assert db.query(Notification).count() > before['notifications']
        else:
            assert db.query(AuditLog).count() > before['audit_logs']
        reached.append(True)
        raise RuntimeError('reviewer late sales participant failure')

    monkeypatch.setattr(module, name, fail_after_real_write)
    payload = {'order_type': 'branded_stock_sale', 'items': [
        {'model_id': model_id, 'brand_id': brand_id, 'color': 'white', 'size': '46',
         'quantity': 12, 'unit_price': 19}]}
    with pytest.raises(RuntimeError, match='reviewer late sales participant failure'):
        client.post('/api/sales-orders', headers=auth_headers, json=payload)
    assert reached == [True], 'The test must fail after real stock and participant writes'
    assert _counts() == before
    assert stock_state(stock_id) == prior_stock

    monkeypatch.setattr(module, name, original)
    retry = client.post('/api/sales-orders', headers=auth_headers, json=payload)
    assert retry.status_code == 201, retry.text
    assert retry.json()['status'] == 'ready'
    assert stock_state(stock_id)[:2] == (18, 12)
    after = _counts()
    assert after['sales_orders'] == before['sales_orders'] + 1
    assert after['sales_order_items'] == before['sales_order_items'] + 1
    assert after['stock_reservations'] == before['stock_reservations'] + 1
    assert after['audit_logs'] == before['audit_logs'] + 2
    assert after['notifications'] > before['notifications']
    assert after['idempotency_records'] == before['idempotency_records']
