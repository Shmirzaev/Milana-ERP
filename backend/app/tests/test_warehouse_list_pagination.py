from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.inventory import list_warehouses
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, User, Warehouse
from app.schemas.inventory import WarehouseOut


def _seed_warehouses(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        baseline = db.query(Warehouse).count()
        rows = [
            Warehouse(
                name=f"Bounded warehouse {marker} {index:04d}",
                type="fabric_storage",
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows], baseline


def _read(**kwargs):
    with SessionLocal() as db:
        user = db.get(User, 1)
        assert user is not None
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_warehouses(db, user, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[Warehouse]) -> list[dict]:
    return [WarehouseOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_warehouse_pages_bound_rows_and_preserve_legacy_payload(count):
    created_ids, baseline = _seed_warehouses(count)

    page, statements = _read(page=1, page_size=count)
    legacy, legacy_statements = _read(page=None, page_size=None)

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is (baseline > 0)
    assert [row.id for row in page["rows"]] == [row.id for row in legacy[:count]]
    assert created_ids == [row.id for row in legacy[-count:]]
    assert _payload(page["rows"]) == _payload(legacy[:count])
    assert len(statements) == 2, statements
    assert len(legacy_statements) == 1, legacy_statements


def test_warehouse_page_scopes_before_count_and_has_no_write_side_effects(client):
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        user = User(
            name=f"Materials reader {marker}",
            email=f"materials-reader-{marker}@example.com",
            password_hash="not-used",
            factory_code="MIL",
            extra_permissions=["storage.items", "inventory.materials_only"],
            is_active=True,
        )
        fabric = Warehouse(name=f"Visible fabric {marker}", type="fabric_storage")
        accessory = Warehouse(name=f"Hidden accessory {marker}", type="accessory_storage")
        db.add_all([user, fabric, accessory])
        db.commit()
        user_id = int(user.id)
        fabric_id = int(fabric.id)
        accessory_id = int(accessory.id)
        expected_total = db.query(Warehouse).filter(Warehouse.type != "accessory_storage").count()
        before = (db.query(Warehouse).count(), db.query(AuditLog).count())

    headers = {
        "Authorization": f"Bearer {create_access_token(user_id, {'factory_code': 'MIL'})}",
    }
    response = client.get(
        "/api/inventory/warehouses",
        params={"page": 1, "page_size": 500},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == expected_total
    assert fabric_id in [row["id"] for row in payload["rows"]]
    assert accessory_id not in [row["id"] for row in payload["rows"]]
    assert all(row["type"] != "accessory_storage" for row in payload["rows"])
    assert client.get(
        "/api/inventory/warehouses",
        params={"page": 1, "page_size": 501},
        headers=headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/inventory/warehouses",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(Warehouse).count(), db.query(AuditLog).count())
    assert after == before
