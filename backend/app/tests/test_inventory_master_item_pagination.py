"""Inventory Master Data searches complete item catalogs before paging."""

from uuid import uuid4

from sqlalchemy import event

from app.api.routes.inventory import list_items
from app.db.session import SessionLocal
from app.models import Item


def test_master_item_search_pages_401_rows_and_finds_off_page_composition(monkeypatch):
    marker = uuid4().hex[:8].upper()
    monkeypatch.setattr("app.api.routes.inventory.inventory_access.scoped_group", lambda _user, group, _category: group)
    with SessionLocal() as db:
        db.add_all([
            Item(
                sku=f"MASTER-PAGE-{marker}-{index:04d}",
                name=f"Master item {marker} {index:04d}",
                category="fabric",
                unit="kg",
                composition_json=[{"name": "UniqueCottonFiber", "percentage": 50}] if index == 0 else [],
            )
            for index in range(401)
        ])
        db.commit()

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            first = list_items(
                db, object(), group="materials", q=marker, page=1, page_size=50,
                include_total=True, master_data_search=True,
            )
            second = list_items(
                db, object(), group="materials", q=marker, page=2, page_size=50,
                include_total=True, master_data_search=True,
            )
            composition = list_items(
                db, object(), group="materials", q="UniqueCottonFiber", page=1,
                page_size=50, include_total=True, master_data_search=True,
            )
            formatted_composition = list_items(
                db, object(), group="materials", q="UniqueCottonFiber 50%", page=1,
                page_size=50, include_total=True, master_data_search=True,
            )
            legacy = list_items(
                db, object(), group="materials", q="UniqueCottonFiber", page=1,
                page_size=50, include_total=True,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert first["total"] == second["total"] == 401
    assert len(first["rows"]) == len(second["rows"]) == 50
    assert {row["id"] for row in first["rows"]}.isdisjoint(row["id"] for row in second["rows"])
    assert composition["total"] == 1
    assert composition["rows"][0]["composition"][0]["name"] == "UniqueCottonFiber"
    assert formatted_composition["rows"][0]["id"] == composition["rows"][0]["id"]
    assert legacy["total"] == 0
    row_selects = [sql for sql in statements if " from items " in sql and " limit ? offset ?" in sql]
    assert len(row_selects) == 5
    assert not any(sql.startswith(("insert", "update", "delete")) for sql in statements)


def test_master_item_page_keeps_auth_and_legacy_shape(client, auth_headers):
    path = "/api/inventory/items?group=materials&page=1&page_size=50&include_total=true&master_data_search=true"
    assert client.get(path).status_code == 401
    page = client.get(path, headers=auth_headers)
    assert page.status_code == 200, page.text
    assert isinstance(page.json()["rows"], list)
    assert isinstance(page.json()["total"], int)
    legacy = client.get("/api/inventory/items?group=materials&page_size=50", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
