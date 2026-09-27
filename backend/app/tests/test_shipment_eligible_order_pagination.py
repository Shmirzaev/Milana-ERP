from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.shipments import eligible_orders
from app.db.session import SessionLocal
from app.models import AuditLog, Customer, Model, Package, ProductionOrder, SalesOrder, Shipment, User


def _seed_eligible_orders(count: int) -> list[int]:
    marker = uuid4().hex
    with SessionLocal() as db:
        customer = Customer(name=f"Eligible order customer {marker}")
        db.add(customer)
        db.flush()
        model_id = int(db.query(Model.id).order_by(Model.id).first()[0])
        production_order = ProductionOrder(
            production_no=f"PERF35-ELIGIBLE-{marker}",
            production_type="branded_stock",
            model_id=model_id,
            planned_quantity=count,
        )
        db.add(production_order)
        db.flush()
        orders = [
            SalesOrder(
                order_no=f"PERF35-ELIGIBLE-{marker}-{index:04d}",
                customer_id=customer.id,
                status="draft",
                total_amount=index + 1,
            )
            for index in range(count)
        ]
        db.add_all(orders)
        db.flush()
        db.add_all(
            [
                Package(
                    package_no=f"PERF35-ELIGIBLE-PKG-{marker}-{index:04d}",
                    barcode=f"PERF35-ELIGIBLE-BC-{marker}-{index:04d}",
                    production_order_id=production_order.id,
                    sales_order_id=order.id,
                    model_id=model_id,
                    color="Blue",
                    total_quantity=index + 1,
                    capacity=60,
                    status="received_in_storage",
                )
                for index, order in enumerate(orders)
            ]
        )
        db.commit()
        return [int(order.id) for order in orders]


def _read(**kwargs):
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = eligible_orders(db, current, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_eligible_order_page_bounds_joined_data_and_matches_legacy_prefix(row_count):
    created_ids = _seed_eligible_orders(row_count)

    legacy, legacy_statements = _read()
    page, page_statements = _read(page=1, page_size=50)

    expected_ids = list(reversed(created_ids))[:50]
    assert [row["id"] for row in page["rows"]][: len(expected_ids)] == expected_ids
    assert page["rows"] == legacy[:50]
    assert page["total"] == len(legacy)
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (len(legacy) > 50)
    assert len(page["rows"]) <= 50
    assert page["rows"][0]["customer_name"].startswith("Eligible order customer")
    assert page["rows"][0]["ready_qty"] == row_count
    assert len(legacy_statements) == 1, legacy_statements
    assert len(page_statements) == 2, page_statements
    row_statement = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert "left outer join (select packages.sales_order_id" in row_statement
    assert "exists (select" in row_statement
    assert "order by sales_orders.id desc" in row_statement
    assert "sales_orders.printing_attachments" not in row_statement
    assert "sales_orders.notes" not in row_statement
    assert "customers.address" not in row_statement
    assert "customers.notes" not in row_statement


def test_eligible_order_page_contract_auth_and_no_writes(client, auth_headers):
    created_ids = _seed_eligible_orders(3)
    with SessionLocal() as db:
        before = (
            db.query(SalesOrder).count(),
            db.query(Package).count(),
            db.query(Shipment).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get("/api/shipments/eligible-orders", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/shipments/eligible-orders",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()[2:4]
    assert payload["rows"][0]["id"] == created_ids[0]
    assert payload["total"] == len(legacy.json())
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is (len(legacy.json()) > 4)

    assert client.get(
        "/api/shipments/eligible-orders",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/shipments/eligible-orders",
        params={"page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (
            db.query(SalesOrder).count(),
            db.query(Package).count(),
            db.query(Shipment).count(),
            db.query(AuditLog).count(),
        )
    assert after == before
