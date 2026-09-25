from uuid import uuid4

from sqlalchemy import event

from app.api.routes.shipments import eligible_orders, list_shipments, shipment_order_floor
from app.db.session import SessionLocal
from app.models import Customer, Package, Shipment, ShipmentPackage, User
from app.tests.test_shipment_eligible_order_pagination import _seed_eligible_orders


def _capture(db, operation):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return operation(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


def test_order_floor_pages_exact_mixed_union_search_and_off_page_targets(client, auth_headers):
    order_ids = _seed_eligible_orders(421)
    marker = uuid4().hex
    with SessionLocal() as db:
        override_customer = Customer(name=f"Override floor customer {marker}")
        db.add(override_customer)
        db.flush()
        older = Shipment(sales_order_id=order_ids[0], shipment_no=f"FLOOR-OLDER-{marker}", status="created")
        latest = Shipment(
            sales_order_id=order_ids[0], customer_id=override_customer.id,
            shipment_no=f"FLOOR-LATEST-{marker}", status="draft",
        )
        shipped = Shipment(sales_order_id=order_ids[1], shipment_no=f"FLOOR-SHIPPED-{marker}", status="shipped")
        cancelled = Shipment(sales_order_id=order_ids[2], shipment_no=f"FLOOR-CANCELLED-{marker}", status="cancelled")
        manual = Shipment(customer_id=override_customer.id, shipment_no=f"FLOOR-MANUAL-{marker}", status="created")
        db.add_all((older, latest, shipped, cancelled, manual))
        db.flush()
        older_id = int(older.id)
        shipped_id = int(shipped.id)
        db.add_all(
            Shipment(customer_id=override_customer.id, shipment_no=f"FLOOR-RECENT-{index}-{marker}", status="delivered")
            for index in range(55)
        )
        package_ids = [row.id for row in db.query(Package.id).order_by(Package.id.desc()).limit(401)]
        db.add_all(ShipmentPackage(shipment_id=latest.id, package_id=package_id, quantity=1) for package_id in package_ids)
        db.commit()
        latest_id = int(latest.id)
        manual_id = int(manual.id)

        current = db.query(User).filter(User.email == "admin@example.com").one()
        legacy_shipments = list_shipments(db, current)
        legacy_eligible = eligible_orders(db, current)
        old_floor_ids = {
            int(shipment["sales_order_id"])
            for shipment in legacy_shipments
            if shipment["sales_order_id"] and shipment["status"] in ("draft", "created")
        } | {int(order["id"]) for order in legacy_eligible}
        expected_total = len(old_floor_ids)
        first, statements = _capture(db, lambda: shipment_order_floor(db, current, page=1, page_size=50))
        assert first["total"] == expected_total
        assert len(first["rows"]) == 50
        assert first["has_more"] is True
        assert [row["id"] for row in first["rows"]] == list(reversed(order_ids))[:50]
        assert len(statements) <= 8, statements
        assert not any("shipment_packages.id as" in statement for statement in statements)

        last, _ = _capture(db, lambda: shipment_order_floor(db, current, page=9, page_size=50))
        assert last["total"] == expected_total
        assert len(last["rows"]) == expected_total - 400
        assert order_ids[1] not in {row["id"] for row in last["rows"]}

        pinned, _ = _capture(db, lambda: shipment_order_floor(
            db, current, page=1, page_size=50, target_shipment_id=latest_id,
        ))
        assert pinned["pinned"]["id"] == order_ids[0]
        assert pinned["pinned"]["shipment"]["id"] == latest_id
        assert pinned["pinned"]["ready_qty"] == 401
        assert pinned["pinned"]["customer_name"] == override_customer.name
        assert pinned["total"] == expected_total
        assert len(pinned["rows"]) == 50

        customer_search, _ = _capture(db, lambda: shipment_order_floor(
            db, current, page=1, page_size=50, q=f"Override floor customer {marker}",
        ))
        assert [row["id"] for row in customer_search["rows"]] == [order_ids[0]]
        assert customer_search["total"] == 1
        shipment_search, _ = _capture(db, lambda: shipment_order_floor(
            db, current, page=1, page_size=50, q=f"FLOOR-LATEST-{marker}",
        ))
        assert [row["id"] for row in shipment_search["rows"]] == [order_ids[0]]

        history, history_statements = _capture(db, lambda: list_shipments(
            db, current, page=1, page_size=50, q=f"FLOOR-MANUAL-{marker}",
        ))
        assert history["total"] == 1
        assert history["rows"][0]["id"] == manual_id
        assert len(history_statements) <= 5, history_statements
        active_history, active_statements = _capture(db, lambda: list_shipments(
            db, current, page=1, page_size=50, q=f"FLOOR-LATEST-{marker}",
        ))
        assert active_history["rows"][0]["packages_count"] == 401
        assert active_history["rows"][0]["total_qty"] == 401
        assert not any("shipment_packages.id as" in statement for statement in active_statements)
        manual_page, _ = _capture(db, lambda: list_shipments(
            db, current, page=1, page_size=50, manual_open=True,
        ))
        assert manual_id in {row["id"] for row in manual_page["rows"]}
        assert latest_id not in {row["id"] for row in manual_page["rows"]}
        first_history = list_shipments(db, current, page=1, page_size=50)
        assert shipped_id not in {row["id"] for row in first_history["rows"]}
        assert older_id not in {row["id"] for row in first_history["rows"]}
        for target_id in (shipped_id, older_id):
            target_page, target_statements = _capture(db, lambda: list_shipments(
                db, current, page=1, page_size=1, shipment_id=target_id,
            ))
            assert target_page["total"] == 1
            assert [row["id"] for row in target_page["rows"]] == [target_id]
            assert len(target_statements) <= 5, target_statements

    http_page = client.get(
        "/api/shipments/order-floor",
        params={"page": 1, "page_size": 50, "target_sales_order_id": order_ids[0]},
        headers=auth_headers,
    )
    assert http_page.status_code == 200, http_page.text
    assert http_page.json()["total"] == expected_total
    assert http_page.json()["pinned"]["id"] == order_ids[0]
    history_target = client.get(
        "/api/shipments", params={"shipment_id": shipped_id, "page": 1, "page_size": 1}, headers=auth_headers,
    )
    assert history_target.status_code == 200, history_target.text
    assert [row["id"] for row in history_target.json()["rows"]] == [shipped_id]
    assert client.get(f"/api/shipments?shipment_id={shipped_id}&page_size=1").status_code == 401
    assert client.get("/api/shipments/order-floor?page_size=101", headers=auth_headers).status_code == 422
    assert client.get("/api/shipments/order-floor").status_code == 401
