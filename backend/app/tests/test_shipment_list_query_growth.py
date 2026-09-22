from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.shipments import list_shipments
from app.db.session import SessionLocal
from app.models import Customer, Model, Package, ProductionOrder, SalesOrder, Shipment, ShipmentPackage, ShipmentScanLog


def _seed(count):
    marker = uuid4().hex
    with SessionLocal() as db:
        buyers = [Customer(name=f"Shipment buyer {marker}-{i}") for i in range(count)]
        db.add_all(buyers)
        db.flush()
        orders = [SalesOrder(order_no=f"SQL-SO-{marker}-{i}", customer_id=buyer.id)
                  for i, buyer in enumerate(buyers)]
        db.add_all(orders)
        db.flush()
        shipments = [Shipment(shipment_no=f"SQL-SH-{marker}-{i}", sales_order_id=order.id)
                     for i, order in enumerate(orders)]
        db.add_all(shipments)
        db.commit()
        return [(row.id, order.id, order.order_no, buyer.name)
                for row, order, buyer in zip(shipments, orders, buyers)]


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, *_):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_shipments(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize(("count", "expected"), [(1, 3), (50, 3), (501, 4)])
def test_shipment_list_batches_distinct_order_and_customer_references(count, expected):
    seeded = _seed(count)
    rows, statements = _read()
    assert [row["id"] for row in rows] == [row[0] for row in reversed(seeded)]
    for row, (_, order_id, order_no, buyer_name) in zip(rows, reversed(seeded)):
        assert row["sales_order_id"] == order_id
        assert row["sales_order_no"] == order_no
        assert row["customer_name"] == buyer_name
        assert row["packages_count"] == row["total_qty"] == row["scanned_count"] == 0
        assert row["shipment_type"] == "sales_order"
        assert row["is_complete"] is False
    assert len(statements) == expected


@pytest.mark.parametrize("count", [1, 50, 401])
def test_shipment_list_opt_in_pages_bound_rows_and_query_growth(count):
    with SessionLocal() as db:
        baseline = db.query(Shipment).count()
    seeded = _seed(count)

    page, statements = _read(page=1, page_size=count)

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert len(page["rows"]) == count
    assert [row["id"] for row in page["rows"]] == [row[0] for row in reversed(seeded)]
    assert page["has_more"] is (baseline > 0)
    assert len(statements) == 4, statements


def test_shipment_list_customer_override_nulls_and_order_filter():
    seeded = _seed(2)
    with SessionLocal() as db:
        override = Customer(name=f"Manual override {uuid4().hex}")
        db.add(override)
        db.flush()
        db.get(Shipment, seeded[0][0]).customer_id = override.id
        manual = Shipment(shipment_no=f"MAN-{uuid4().hex}", customer_id=override.id,
                          dispatch_snapshot={"manual": True})
        empty = Shipment(shipment_no=f"EMPTY-{uuid4().hex}")
        db.add_all([manual, empty])
        db.commit()
        manual_id, empty_id, name = manual.id, empty.id, override.name
    rows, _ = _read()
    by_id = {row["id"]: row for row in rows}
    assert by_id[seeded[0][0]]["customer_name"] == name
    assert by_id[manual_id]["customer_name"] == name
    assert by_id[manual_id]["shipment_type"] == "manual"
    assert by_id[empty_id]["customer_name"] is None
    assert by_id[empty_id]["sales_order_no"] is None
    filtered, statements = _read(sales_order_id=seeded[0][1])
    assert [row["id"] for row in filtered] == [seeded[0][0]]
    assert len(statements) == 3


def test_shipment_list_requires_authentication(client):
    assert client.get("/api/shipments").status_code == 401


def test_shipment_list_http_response_keeps_customer_and_order(client, auth_headers):
    shipment_id, order_id, order_no, buyer_name = _seed(1)[0]
    response = client.get("/api/shipments", params={"sales_order_id": order_id}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    row = response.json()[0]
    assert (row["id"], row["sales_order_no"], row["customer_name"]) == (shipment_id, order_no, buyer_name)

    paged = client.get(
        "/api/shipments",
        params={"sales_order_id": order_id, "page": 1, "page_size": 1},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    page = paged.json()
    assert page == {
        "rows": [row],
        "total": 1,
        "page": 1,
        "page_size": 1,
        "has_more": False,
    }


def test_shipment_list_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/shipments",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text


def test_shipment_list_preserves_package_totals_and_valid_scan_counts():
    shipment_id, order_id, _, _ = _seed(1)[0]
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"SHQ-{marker}", name="Shipment count model")
        db.add(model)
        db.flush()
        production = ProductionOrder(production_no=f"SHQPO-{marker}", production_type="client_order",
                                     model_id=model.id, planned_quantity=15)
        db.add(production)
        db.flush()
        packages = [Package(package_no=f"SHQ-{marker}-{i}", barcode=f"SHQBC-{marker}-{i}",
                            production_order_id=production.id, color="navy",
                            model_id=model.id, total_quantity=quantity, capacity=60, status="packed")
                    for i, quantity in enumerate([3, 5, 7])]
        db.add_all(packages)
        db.flush()
        db.add_all([ShipmentPackage(shipment_id=shipment_id, package_id=package.id, quantity=package.total_quantity)
                    for package in packages[:2]])
        for index, result in [(0, "matched"), (0, "matched"), (1, "matched"), (1, "detached"), (2, "matched")]:
            db.add(ShipmentScanLog(shipment_id=shipment_id, package_id=packages[index].id,
                                   scanned_code=packages[index].barcode, scan_result=result))
            db.flush()
        db.commit()
    rows, statements = _read(sales_order_id=order_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["packages_count"] == row["required_count"] == 2
    assert row["total_qty"] == 8
    assert row["scanned_count"] == row["remaining_count"] == 1
    assert row["is_complete"] is False
    assert len(statements) == 3
