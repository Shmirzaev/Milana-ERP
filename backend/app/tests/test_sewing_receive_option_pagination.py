from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

from app.api.routes.bundles import sewing_receive_options
from app.models import AuditLog, Bundle, Model, ProductionOrder
from app.tests.conftest import TestSessionLocal


def _milana_user():
    return SimpleNamespace(
        factory_code="MIL",
        session_factory_code="MIL",
        extra_permissions=[],
        role=None,
    )


def _seed_receive_options(row_count: int) -> list[int]:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        model = Model(
            code=f"SEW-OPTION-{marker}",
            name=f"Sewing option model {marker}",
            product_type="shirt",
            status="approved",
        )
        db.add(model)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"SEW-OPTION-PO-{marker}-{index:04d}",
                production_type="client_order",
                model_id=model.id,
                planned_quantity=1,
                status="sewing",
            )
            for index in range(row_count)
        ]
        db.add_all(orders)
        db.flush()
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        bundles = [
            Bundle(
                bundle_no=f"SEW-OPTION-BND-{marker}-{index:04d}",
                barcode=f"SEW-OPTION-BC-{marker}-{index:04d}",
                production_order_id=orders[index].id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=1,
                sewing_factory_code="MIL",
                status="sent_to_sewing",
                created_at=base_time + timedelta(minutes=index),
            )
            for index in range(row_count)
        ]
        db.add_all(bundles)
        db.commit()
        return [int(order.id) for order in orders]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = sewing_receive_options(db, _milana_user(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_sewing_receive_option_page_bounds_sql_and_preserves_legacy_prefix(row_count):
    order_ids = _seed_receive_options(row_count)

    legacy, legacy_statements = _read(limit=100)
    page, page_statements = _read(limit=100, page=1, page_size=50)

    expected_rows = min(row_count, 50)
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) == expected_rows
    assert jsonable_encoder(page["rows"]) == jsonable_encoder(legacy[:expected_rows])
    assert [row["production_order_id"] for row in page["rows"]] == list(reversed(order_ids))[:expected_rows]
    assert len(legacy_statements) == 5, legacy_statements
    assert len(page_statements) == 6, page_statements
    grouped_page = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert "group by bundles.production_order_id" in grouped_page
    assert all(statement.startswith("select") for statement in page_statements)


def test_sewing_receive_option_page_preserves_auth_scope_validation_and_no_writes(client, auth_headers):
    order_ids = _seed_receive_options(3)
    with TestSessionLocal() as db:
        before = (
            db.query(Bundle).filter(Bundle.production_order_id.in_(order_ids)).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get(
        "/api/bundles/sewing-receive-options?limit=1",
        headers=auth_headers,
    )
    paged = client.get(
        "/api/bundles/sewing-receive-options?page=1&page_size=1",
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert paged.status_code == 200, paged.text
    assert isinstance(legacy.json(), list)
    assert paged.json()["rows"] == legacy.json()
    assert paged.json()["total"] == 3
    assert paged.json()["has_more"] is True

    assert client.get(
        "/api/bundles/sewing-receive-options?page=1&page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/bundles/sewing-receive-options?page=1&page_size=1",
    ).status_code == 401
    assert client.get(
        "/api/bundles/sewing-receive-options?factory_code=BST&page=1&page_size=1",
        headers=auth_headers,
    ).status_code == 403

    with TestSessionLocal() as db:
        after = (
            db.query(Bundle).filter(Bundle.production_order_id.in_(order_ids)).count(),
            db.query(AuditLog).count(),
        )
    assert after == before
