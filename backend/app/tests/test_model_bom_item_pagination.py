from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.catalog import list_model_bom_items
from app.db.session import SessionLocal
from app.models import Item
from app.schemas.inventory import ItemOut


_BOM_CATEGORIES = ("fabric", "semi_finished", "accessory", "packaging")


def _seed_items(count: int) -> int:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        baseline = db.query(Item).filter(
            Item.is_active.is_(True),
            Item.category.in_(_BOM_CATEGORIES),
        ).count()
        db.add_all([
            Item(
                sku=f"PERF35-BOM-{marker}-{number:04d}",
                name=f"Paged BOM item {marker} {number:04d}",
                category=_BOM_CATEGORIES[number % len(_BOM_CATEGORIES)],
                unit="pcs",
                is_active=True,
            )
            for number in range(count)
        ])
        db.commit()
        return baseline


def _serialize_rows(rows):
    return [ItemOut.model_validate(row).model_dump(mode="json") for row in rows]


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_model_bom_items(db, object(), **kwargs)
            if isinstance(payload, dict):
                payload = {**payload, "rows": _serialize_rows(payload["rows"])}
            else:
                payload = _serialize_rows(payload)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("item_count", [1, 50, 401])
def test_bom_item_page_bounds_rows_and_preserves_legacy_order(item_count):
    baseline = _seed_items(item_count)

    page, statements = _read(page=1, page_size=50)
    legacy, legacy_statements = _read()

    selects = [statement for statement in statements if statement.startswith("select")]
    writes = [
        statement for statement in statements
        if statement.startswith(("insert", "update", "delete"))
    ]
    assert page["total"] == baseline + item_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (page["total"] > 50)
    assert page["rows"] == legacy[:50]
    assert len(page["rows"]) == min(page["total"], 50)
    assert len(selects) == 2, selects
    assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 1
    assert writes == []
    item_page_query = next(
        statement for statement in selects
        if " from items " in statement and " limit ? offset ?" in statement
    )
    assert "items.composition_json" in item_page_query
    assert "items.created_at" not in item_page_query
    assert "items.updated_at" not in item_page_query


def test_bom_item_page_http_contract_and_authorization(client, auth_headers):
    legacy = client.get("/api/models/bom-items", headers=auth_headers)
    paged = client.get(
        "/api/models/bom-items",
        params={"page": 1, "page_size": 50},
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == 200
    payload = paged.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["has_more"] is (payload["total"] > 50)
    assert client.get("/api/models/bom-items?page=1&page_size=1").status_code == 401

    denied_login = client.post(
        "/api/auth/token",
        data={"username": "storage@example.com", "password": "demo12345"},
    )
    assert denied_login.status_code == 200, denied_login.text
    denied = client.get(
        "/api/models/bom-items?page=1&page_size=1",
        headers={"Authorization": f"Bearer {denied_login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text


def test_bom_item_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/models/bom-items",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
