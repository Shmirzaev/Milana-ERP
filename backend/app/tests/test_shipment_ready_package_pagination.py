from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

from app.api.routes.shipments import ready_packages
from app.models import AuditLog, Model, Package, ProductionOrder, SalesOrder
from app.tests.conftest import TestSessionLocal


def _seed_ready_packages(row_count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        model = Model(
            code=f"READY-PAGE-{marker}",
            name=f"Ready package model {marker}",
            product_type="shirt",
            status="approved",
        )
        sales_order = SalesOrder(
            order_no=f"READY-PAGE-SO-{marker}",
            order_type="client_order",
            status="ready",
            total_amount=0,
        )
        db.add_all([model, sales_order])
        db.flush()
        production_order = ProductionOrder(
            production_no=f"READY-PAGE-PO-{marker}",
            production_type="client_order",
            sales_order_id=sales_order.id,
            model_id=model.id,
            planned_quantity=row_count,
            status="storage",
        )
        db.add(production_order)
        db.flush()
        packages = [
            Package(
                package_no=f"READY-PAGE-PKG-{marker}-{index:04d}",
                barcode=f"READY-PAGE-BC-{marker}-{index:04d}",
                production_order_id=production_order.id,
                sales_order_id=sales_order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=60,
                status="received_in_storage",
            )
            for index in range(row_count)
        ]
        db.add_all(packages)
        db.commit()
        return int(sales_order.id), [int(package.id) for package in packages]


def _read(sales_order_id: int, **kwargs):
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = ready_packages(db, object(), sales_order_id=sales_order_id, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_ready_package_page_bounds_sql_and_preserves_legacy_prefix(row_count):
    sales_order_id, package_ids = _seed_ready_packages(row_count)

    legacy, legacy_statements = _read(sales_order_id)
    page, page_statements = _read(sales_order_id, page=1, page_size=50)

    expected_rows = min(row_count, 50)
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) == expected_rows
    assert jsonable_encoder(page["rows"]) == jsonable_encoder(legacy[:expected_rows])
    assert [row["id"] for row in page["rows"]] == package_ids[:expected_rows]
    assert len(legacy_statements) == 2, legacy_statements
    assert len(page_statements) == 2, page_statements
    assert " limit ? offset ?" in page_statements[-1]


def test_ready_package_page_preserves_auth_validation_and_no_writes(client, auth_headers):
    sales_order_id, package_ids = _seed_ready_packages(3)
    with TestSessionLocal() as db:
        before = (
            db.query(Package).filter(Package.id.in_(package_ids)).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get(
        f"/api/shipments/ready-packages?sales_order_id={sales_order_id}",
        headers=auth_headers,
    )
    paged = client.get(
        f"/api/shipments/ready-packages?sales_order_id={sales_order_id}&page=1&page_size=1",
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert paged.status_code == 200, paged.text
    assert isinstance(legacy.json(), list)
    assert paged.json()["rows"] == legacy.json()[:1]
    assert paged.json()["total"] == 3
    assert paged.json()["has_more"] is True

    legacy_general = client.get(
        "/api/shipments/ready-packages?sales_order_id=0",
        headers=auth_headers,
    )
    paged_general = client.get(
        "/api/shipments/ready-packages?sales_order_id=0&page=1&page_size=500",
        headers=auth_headers,
    )
    assert paged_general.status_code == 200, paged_general.text
    assert paged_general.json()["rows"] == legacy_general.json()[:500]
    assert paged_general.json()["total"] == len(legacy_general.json())

    assert client.get(
        f"/api/shipments/ready-packages?sales_order_id={sales_order_id}&page=1&page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        f"/api/shipments/ready-packages?sales_order_id={sales_order_id}&page=1&page_size=1",
    ).status_code == 401

    with TestSessionLocal() as db:
        after = (
            db.query(Package).filter(Package.id.in_(package_ids)).count(),
            db.query(AuditLog).count(),
        )
    assert after == before
