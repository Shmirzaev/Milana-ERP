"""Missing raw-vocabulary witnesses; synthetic SQLite, no mapper change."""
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.libs.dto.sales.sales_order_output import SalesOrderDetail
from app.models.sales import orders_service
from app.schemas import AuditLog, Notification, SalesOrder, SalesOrderItem
from test_omx_sales_confirm_characterization import setup  # noqa: F401


@pytest.mark.parametrize('surface', ['direct', 'http'])
def test_unknown_item_source_is_not_validated_by_confirm_summary(setup, surface):
    db, actor, _customer, _model, order, client = setup
    engine, order_id = db.get_bind(), order.id
    line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
    line_id = line.id
    line.source_type = 'legacy_unknown'
    db.commit()

    if surface == 'direct':
        result = orders_service.confirm_sales_order(order_id, db, actor)
        assert result['status'] == 'confirmed'
        assert 'items' not in result
    else:
        response = client.post(f'/api/sales-orders/{order_id}/confirm')
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'confirmed'
        assert 'items' not in response.json()

    with pytest.raises(ValidationError) as caught:
        if surface == 'direct':
            orders_service.get_sales_order(order_id, db)
        else:
            client.get(f'/api/sales-orders/{order_id}')
    assert ('items', 0, 'source_type') in [error['loc'] for error in caught.value.errors()]
    db.close()
    with Session(engine) as fresh:
        assert fresh.get(SalesOrder, order_id).status == 'confirmed'
        loaded = fresh.get(SalesOrderItem, line_id)
        assert type(loaded.source_type) is str
        assert loaded.source_type == 'legacy_unknown'
        assert fresh.query(AuditLog).filter_by(action='confirm', entity_id=order_id).count() == 1
        assert fresh.query(Notification).count() == 0


@pytest.mark.parametrize('order_type,source_type', [
    ('legacy_unknown', 'legacy_unknown'),
    (' CLIENT_ORDER ', ' FROM_STOCK '),
    ('CLIENT_ORDER', 'FIRST_GRADE'),
])
def test_noncanonical_storage_stays_raw_until_detail_validation(setup, order_type, source_type):
    db, _actor, _customer, _model, order, _client = setup
    engine, order_id = db.get_bind(), order.id
    line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
    line_id = line.id
    order.order_type, line.source_type = order_type, source_type
    db.commit()
    db.close()
    with Session(engine) as fresh:
        loaded = fresh.get(SalesOrder, order_id)
        loaded_line = fresh.get(SalesOrderItem, line_id)
        assert type(loaded.order_type) is str and loaded.order_type == order_type
        assert type(loaded_line.source_type) is str and loaded_line.source_type == source_type
        with pytest.raises(ValidationError) as caught:
            SalesOrderDetail.model_validate(loaded)
        locations = [error['loc'] for error in caught.value.errors()]
        assert ('order_type',) in locations
        assert ('items', 0, 'source_type') in locations
