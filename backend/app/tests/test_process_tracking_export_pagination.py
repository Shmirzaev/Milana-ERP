import re
from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import AuditLog, Customer, Model, ProductionOrder, SalesOrder
from app.tests.conftest import test_engine


def _seed_active_orders(count: int) -> tuple[list[int], list[str]]:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        db.query(ProductionOrder).filter(
            ProductionOrder.status.not_in(("closed", "cancelled", "delivered")),
        ).update({ProductionOrder.status: "closed"}, synchronize_session=False)

        customers = [Customer(name=f"Export customer {marker} {index:04d}") for index in range(count)]
        models = [
            Model(
                code=f"EXPORT-MODEL-{marker}-{index:04d}",
                name=f"Export model {index:04d}",
                status="approved",
            )
            for index in range(count)
        ]
        db.add_all([*customers, *models])
        db.flush()
        sales_orders = [
            SalesOrder(
                order_no=f"EXPORT-SO-{marker}-{index:04d}",
                customer_id=customers[index].id,
                order_type="client_order",
                status="in_production",
                total_amount=0,
            )
            for index in range(count)
        ]
        db.add_all(sales_orders)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF35-EXPORT-{marker}-{index:04d}",
                production_type="client_order",
                sales_order_id=sales_orders[index].id,
                model_id=models[index].id,
                status="new",
                planned_quantity=index + 1,
            )
            for index in range(count)
        ]
        db.add_all(orders)
        db.commit()
        return [int(row.id) for row in orders], [row.production_no for row in orders]


def _capture_export(client, auth_headers, *, page: int, page_size: int):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/process-tracking/export",
            params={"page": page, "page_size": page_size},
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return response, statements


def _production_numbers(body: str) -> list[str]:
    return re.findall(r"PERF35-EXPORT-[A-F0-9]+-\d{4}", body)


def test_process_tracking_export_page_is_sql_bounded_at_1_50_and_401_rows(client, auth_headers):
    query_counts: list[int] = []
    for count in (1, 50, 401):
        _ids, production_numbers = _seed_active_orders(count)
        response, statements = _capture_export(client, auth_headers, page=1, page_size=25)

        assert response.status_code == 200, response.text
        expected = list(reversed(production_numbers))[:25]
        assert _production_numbers(response.text) == expected
        assert response.headers["X-Total-Count"] == str(count)
        assert response.headers["X-Page"] == "1"
        assert response.headers["X-Page-Size"] == "25"
        assert response.headers["X-Has-More"] == ("true" if count > 25 else "false")
        production_reads = [statement for statement in statements if " from production_orders " in statement]
        assert any(" limit ? offset ?" in statement for statement in production_reads), production_reads
        query_counts.append(len(statements))

    print(f"Process tracking export SELECTs at 1/50/401 rows: {query_counts}")
    assert max(query_counts) - min(query_counts) <= 1, query_counts


def test_process_tracking_export_page_matches_legacy_order_and_enrichment(client, auth_headers):
    _ids, production_numbers = _seed_active_orders(55)
    legacy = client.get("/api/process-tracking/export", headers=auth_headers)
    paged = client.get(
        "/api/process-tracking/export",
        params={"page": 2, "page_size": 20},
        headers=auth_headers,
    )

    assert legacy.status_code == 200, legacy.text
    assert paged.status_code == 200, paged.text
    assert "X-Total-Count" not in legacy.headers
    assert _production_numbers(legacy.text) == list(reversed(production_numbers))
    assert _production_numbers(paged.text) == list(reversed(production_numbers))[20:40]
    for index in range(15, 35):
        assert f"EXPORT-SO-{production_numbers[index].split('-')[-2]}-{index:04d}" in paged.text
        assert f"Export customer {production_numbers[index].split('-')[-2]} {index:04d}" in paged.text
        assert f"EXPORT-MODEL-{production_numbers[index].split('-')[-2]}-{index:04d}" in paged.text


def test_process_tracking_export_page_auth_validation_and_no_writes(client, auth_headers):
    _seed_active_orders(3)
    with SessionLocal() as db:
        before = (
            db.query(ProductionOrder).count(),
            db.query(Model).count(),
            db.query(SalesOrder).count(),
            db.query(Customer).count(),
            db.query(AuditLog).count(),
        )

    assert client.get(
        "/api/process-tracking/export",
        params={"page": 1, "page_size": 2},
    ).status_code == 401
    assert client.get(
        "/api/process-tracking/export",
        params={"page": 0, "page_size": 2},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/process-tracking/export",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    allowed = client.get(
        "/api/process-tracking/export",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.headers["X-Total-Count"] == "3"

    with SessionLocal() as db:
        after = (
            db.query(ProductionOrder).count(),
            db.query(Model).count(),
            db.query(SalesOrder).count(),
            db.query(Customer).count(),
            db.query(AuditLog).count(),
        )
    assert after == before
