from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import find_on_storage_map
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Model, Package, ProductionOrder, Role, User


def _seed_storage_matches(count: int) -> tuple[list[int], str]:
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"MAP-{marker}", name=f"Storage map {marker}")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"MAP-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        packages = [
            Package(
                package_no=f"MAP-{marker}-{index:04d}",
                barcode=f"MAP-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="Blue",
                total_quantity=index + 1,
                capacity=60,
                status="received_in_storage",
                storage_cell="A-01",
                storage_shelf="1",
            )
            for index in range(count)
        ]
        db.add_all(packages)
        db.commit()
        return [int(package.id) for package in packages], marker


def _read(marker: str, **kwargs):
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = find_on_storage_map(db, None, marker, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_storage_map_find_page_bounds_joined_model_and_matches_legacy_prefix(row_count):
    created_ids, marker = _seed_storage_matches(row_count)

    legacy, legacy_statements = _read(marker)
    page, page_statements = _read(marker, page=1, page_size=50)

    expected_ids = list(reversed(created_ids))[:50]
    assert [row["id"] for row in page["rows"]] == expected_ids
    assert page["rows"] == legacy[:50]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert all(row["model_code"] == f"MAP-{marker}" for row in page["rows"])
    assert all(row["location"] == "A-01/1" for row in page["rows"])
    assert len(legacy_statements) == 1, legacy_statements
    assert len(page_statements) == 2, page_statements
    row_statement = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert " join models " in row_statement
    assert "order by packages.storage_cell asc, packages.storage_shelf asc, packages.id desc" in row_statement


def test_storage_map_find_page_contract_auth_and_no_writes(client):
    created_ids, marker = _seed_storage_matches(3)
    with SessionLocal() as db:
        role = Role(name=f"Storage map reader {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        reader = User(
            name="Storage map reader",
            email=f"storage-map-reader-{uuid4().hex}@example.com",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(reader)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        before = (db.query(Package).count(), db.query(AuditLog).count())

    legacy = client.get(
        "/api/packages/storage-map/find",
        params={"q": marker},
        headers=headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/packages/storage-map/find",
        params={"q": marker, "page": 2, "page_size": 2},
        headers=headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()[2:4]
    assert payload["rows"][0]["id"] == created_ids[0]
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False

    assert client.get(
        "/api/packages/storage-map/find",
        params={"q": marker, "page": 1, "page_size": 501},
        headers=headers,
    ).status_code == 422
    assert client.get(
        "/api/packages/storage-map/find",
        params={"q": marker, "page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (db.query(Package).count(), db.query(AuditLog).count())
    assert after == before
