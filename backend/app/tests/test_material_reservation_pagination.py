from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.inventory import list_material_reservations
from app.models import AuditLog, Item, MaterialReservation, Model, ProductionOrder, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


def _inventory_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=["*"]),
        extra_permissions=[],
    )


@contextmanager
def _reservation_database(count: int):
    engine = create_engine("sqlite://")
    for model in (Item, StockBatch, Warehouse, MaterialReservation):
        model.__table__.create(engine)
    created_at = datetime(2090, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as db:
        reservations = [
            MaterialReservation(
                reservation_no=f"PERF35-{index:04d}",
                production_order_id=777,
                item_id=1,
                reserved_quantity=1,
                consumed_quantity=0,
                released_quantity=0,
                unit="kg",
                status="reserved",
                reservation_type="material",
                source="manual",
                reserved_at=created_at + timedelta(seconds=index),
            )
            for index in range(count)
        ]
        db.add_all(reservations)
        db.commit()
        yield db, [int(reservation.id) for reservation in reservations]
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_material_reservations(
            db,
            _inventory_user(),
            production_order_id=777,
            status="reserved",
            **kwargs,
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_material_reservation_pages_bound_sql_and_preserve_legacy_payload(count):
    with _reservation_database(count) as (db, reservation_ids):
        page, statements = _read(db, page=1, page_size=50)
        legacy, legacy_statements = _read(db, page=None, page_size=None)
        expected_count = min(count, 50)

        assert page["total"] == count
        assert page["page"] == 1
        assert page["page_size"] == 50
        assert page["has_more"] is (count > 50)
        assert [row["id"] for row in page["rows"]] == list(reversed(reservation_ids))[:expected_count]
        assert page["rows"] == legacy[:expected_count]
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_material_reservation_page_contract_filters_auth_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF35-{marker}", name="PERF35 reservation model", status="draft")
        item = Item(
            sku=f"PERF35-{marker}",
            name="PERF35 reservation item",
            category="fabric",
            unit="kg",
            is_active=True,
        )
        db.add_all([model, item])
        db.flush()
        production_order = ProductionOrder(
            production_no=f"PERF35-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=1,
        )
        db.add(production_order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"PERF35-{marker}",
            production_order_id=production_order.id,
            item_id=item.id,
            reserved_quantity=1,
            consumed_quantity=0,
            released_quantity=0,
            unit=item.unit,
            status="reserved",
            reservation_type="material",
            source="manual",
        )
        db.add(reservation)
        db.commit()
        production_order_id = int(production_order.id)
        reservation_id = int(reservation.id)
        before = (db.query(MaterialReservation).count(), db.query(AuditLog).count())

    params = {"production_order_id": production_order_id, "status": "reserved"}
    legacy = client.get("/api/inventory/reservations", params=params, headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert reservation_id in {row["id"] for row in legacy.json()}

    response = client.get(
        "/api/inventory/reservations",
        params={**params, "page": 1, "page_size": 50},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_more"] is (payload["total"] > 50)

    assert client.get(
        "/api/inventory/reservations?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/inventory/reservations?page=1&page_size=1").status_code == 401

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/inventory/reservations?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        after = (db.query(MaterialReservation).count(), db.query(AuditLog).count())
    assert after == before
