from uuid import uuid4

from app.models import Model, ProductionOrder
from app.tests.conftest import TestSessionLocal


def test_process_tracking_filters_visible_work_order_orders_before_paging(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF35-WO-{marker}", name="Paged work orders", status="approved")
        db.add(model)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF35-WO-{marker}-{index}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=10,
            )
            for index in range(3)
        ]
        db.add_all(orders)
        db.commit()
        ids = [int(order.id) for order in orders]

    response = client.get(
        "/api/process-tracking",
        params=[
            ("production_order_ids", str(ids[0])),
            ("production_order_ids", str(ids[2])),
            ("page_size", "2"),
            ("include_total", "true"),
        ],
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 2
    assert {int(row["production_order_id"]) for row in page["rows"]} == {ids[0], ids[2]}


def test_process_tracking_order_id_filter_is_bounded(client, auth_headers):
    response = client.get(
        "/api/process-tracking",
        params=[("production_order_ids", str(index)) for index in range(1, 102)],
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
