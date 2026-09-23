from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production import list_pos
from app.db.session import SessionLocal
from app.models import AuditLog, Model, ProductionOrder, SalesOrder


def _seed_orders(count: int) -> tuple[str, int]:
    marker = uuid4().hex[:8].upper()
    production_type = f"perf35-{marker}"
    with SessionLocal() as db:
        model = Model(
            code=f"PERF35-PO-M-{marker}",
            name=f"Paged production model {marker}",
            status="approved",
        )
        db.add(model)
        db.flush()
        db.add_all([
            ProductionOrder(
                production_no=f"PERF35-PO-{marker}-{number:04d}",
                production_type=production_type,
                source_type="standard",
                model_id=model.id,
                planned_quantity=number + 1,
                status="new",
            )
            for number in range(count)
        ])
        db.commit()
        return production_type, int(model.id)


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_pos(db, SimpleNamespace(), **kwargs)
            if isinstance(payload, dict):
                payload = {**payload, "rows": [int(row.id) for row in payload["rows"]]}
            else:
                payload = [int(row.id) for row in payload]
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_production_order_pages_bound_rows_and_preserve_legacy_payload(order_count):
    production_type, _ = _seed_orders(order_count)

    page, statements = _read(
        production_type=production_type,
        page=1,
        page_size=50,
        include_total=True,
    )
    legacy, legacy_statements = _read(
        production_type=production_type,
        page=1,
        page_size=50,
    )

    selects = [statement for statement in statements if statement.startswith("select")]
    writes = [
        statement for statement in statements
        if statement.startswith(("insert", "update", "delete"))
    ]
    assert page == {
        "rows": legacy,
        "total": order_count,
        "page": 1,
        "page_size": 50,
        "has_more": order_count > 50,
    }
    assert len(page["rows"]) == min(order_count, 50)
    assert len(selects) == 3, selects
    assert " limit ? offset ?" in selects[1]
    assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 2
    assert writes == []


def test_production_order_list_projects_sales_order_reference_fields():
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        model = Model(
            code=f"PERF35-PO-SO-M-{marker}",
            name=f"Sales linked production model {marker}",
            status="approved",
        )
        sales_order = SalesOrder(
            order_no=f"SO-PERF35-PO-{marker}",
            status="draft",
            total_amount=0,
        )
        db.add_all([model, sales_order])
        db.flush()
        production_order = ProductionOrder(
            production_no=f"PERF35-PO-SO-{marker}",
            production_type=f"perf35-so-{marker}",
            source_type="standard",
            model_id=model.id,
            sales_order_id=sales_order.id,
            planned_quantity=1,
            status="new",
        )
        db.add(production_order)
        db.commit()
        production_type = production_order.production_type
        sales_order_no = sales_order.order_no

    with SessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = list_pos(db, SimpleNamespace(), production_type=production_type)
            assert rows[0].sales_order_no == sales_order_no
            assert rows[0].order_no == sales_order_no
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    order_query = next(statement for statement in statements if " from production_orders " in statement)
    assert "sales_orders_1.order_no" in order_query
    assert "sales_orders_1.total_amount" not in order_query


def test_production_order_page_contract_auth_filter_and_no_writes(client, auth_headers):
    production_type, _ = _seed_orders(1)
    with SessionLocal() as db:
        before = (db.query(ProductionOrder).count(), db.query(AuditLog).count())

    legacy = client.get(
        "/api/production-orders",
        params={"production_type": production_type, "page": 1, "page_size": 50},
        headers=auth_headers,
    )
    paged = client.get(
        "/api/production-orders",
        params={
            "production_type": production_type,
            "page": 1,
            "page_size": 50,
            "include_total": "true",
        },
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == 200
    payload = paged.json()
    assert payload == {
        "rows": legacy.json(),
        "total": 1,
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }
    assert client.get(
        "/api/production-orders?page=1&page_size=1&include_total=true",
    ).status_code == 401
    assert client.get(
        "/api/production-orders?page_size=501",
        headers=auth_headers,
    ).status_code == 422

    allowed_login = client.post(
        "/api/auth/token",
        data={"username": "cutting@example.com", "password": "demo12345"},
    )
    assert allowed_login.status_code == 200, allowed_login.text
    allowed = client.get(
        "/api/production-orders?page=1&page_size=1&include_total=true",
        headers={"Authorization": f"Bearer {allowed_login.json()['access_token']}"},
    )
    assert allowed.status_code == 200, allowed.text

    denied_login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert denied_login.status_code == 200, denied_login.text
    denied = client.get(
        "/api/production-orders?page=1&page_size=1&include_total=true",
        headers={"Authorization": f"Bearer {denied_login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(ProductionOrder).count(), db.query(AuditLog).count())
    assert after == before
