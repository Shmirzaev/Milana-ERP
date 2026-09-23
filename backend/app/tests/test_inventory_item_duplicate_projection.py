from uuid import uuid4

from sqlalchemy import event

from app.tests.conftest import test_engine


def test_item_sku_duplicate_checks_project_only_id(client, auth_headers):
    suffix = uuid4().hex[:10].upper()

    def body(sku, name):
        return {
            "sku": sku,
            "name": name,
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
        }

    first = client.post(
        "/api/inventory/items",
        json=body(f"FAB-SKU-ONE-{suffix}", f"Duplicate lookup first {suffix}"),
        headers=auth_headers,
    )
    second = client.post(
        "/api/inventory/items",
        json=body(f"FAB-SKU-TWO-{suffix}", f"Duplicate lookup second {suffix}"),
        headers=auth_headers,
    )
    assert first.status_code == second.status_code == 201

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from items " in normalized and "items.sku =" in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        duplicate_create = client.post(
            "/api/inventory/items",
            json=body(first.json()["sku"], f"Duplicate lookup create {suffix}"),
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    assert duplicate_create.status_code == 400
    assert duplicate_create.json()["detail"] == "SKU already exists"
    assert len(statements) == 1, statements
    assert "select items.id " in statements[0]
    assert "items.name" not in statements[0]

    statements.clear()
    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        duplicate_update = client.patch(
            f"/api/inventory/items/{second.json()['id']}",
            json=body(first.json()["sku"], f"Duplicate lookup update {suffix}"),
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    assert duplicate_update.status_code == 400
    assert duplicate_update.json()["detail"] == "SKU already exists"
    assert len(statements) == 1, statements
    assert "select items.id " in statements[0]
    assert "items.name" not in statements[0]
