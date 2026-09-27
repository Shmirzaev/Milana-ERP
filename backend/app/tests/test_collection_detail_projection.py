"""Collection detail omits its unrelated eager brand join."""
from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Brand, Collection
from app.tests.conftest import test_engine


def test_collection_detail_avoids_unused_brand_columns_and_join(client, auth_headers):
    suffix = uuid4().hex
    with SessionLocal() as db:
        brand = Brand(name=f"Collection projection brand {suffix}")
        db.add(brand)
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"Collection projection {suffix}",
            season="Autumn",
            year=2026,
            description="Collection details",
            status="active",
        )
        db.add(collection)
        db.commit()
        collection_id = collection.id
        brand_id = brand.id

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from collections " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/collections/{collection_id}", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": collection_id,
        "brand_id": brand_id,
        "name": f"Collection projection {suffix}",
        "season": "Autumn",
        "year": 2026,
        "description": "Collection details",
        "status": "active",
    }
    assert len(statements) == 1
    assert " join brands " not in statements[0]
