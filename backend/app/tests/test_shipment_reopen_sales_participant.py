from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.libs.dto.fulfillment.shipment_review import ShipmentReopen
from app.models.shipment_reopen_service import reopen_shipment
from app.schemas import SalesOrder, Shipment, User
from app.tests.test_shipment_reopen import _ship_manual_order_with_invoice, payload
from app.tests.test_shipment_review import dispatch  # noqa: F401
from app.tests.test_package_workflows import warehouse  # noqa: F401


@pytest.mark.parametrize("manual", [False, True])
def test_reopen_sales_fields_rollback_with_outer_transaction(client, auth_headers, warehouse, request, manual):
    if manual:
        _, sid, _, shipped, _ = _ship_manual_order_with_invoice(client, warehouse)
        order_id = shipped.json()["sales_order_id"]
    else:
        case = request.getfixturevalue("dispatch")
        sid, order_id = case["shipment"], case["order"]
        shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
        assert shipped.status_code == 200, shipped.text

    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="fgs@example.com").one()
        order = db.get(SalesOrder, order_id)
        before = (order.status, order.total_amount)
        result = reopen_shipment(db, sid, ShipmentReopen.model_validate(payload(shipped.json())), actor)
        assert order.status == ("cancelled" if manual else "ready_to_ship")
        assert order.total_amount == (Decimal("0") if manual else before[1])
        assert result.sales_order_id == (None if manual else order_id)
        assert db.in_transaction()
        db.rollback()

    with SessionLocal() as db:
        order = db.get(SalesOrder, order_id)
        assert (order.status, order.total_amount) == before
        shipment = db.get(Shipment, sid)
        assert shipment.status == "shipped"
        assert shipment.sales_order_id == order_id
