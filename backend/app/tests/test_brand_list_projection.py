from uuid import uuid4

from sqlalchemy import event

from app.models import Brand
from app.tests.conftest import TestSessionLocal


def test_brand_list_projects_only_brand_response_fields(client, auth_headers):
    name = f"Brand projection {uuid4().hex[:12]}"
    with TestSessionLocal() as db:
        brand = Brand(
            name=name,
            description="projected description",
            logo_url="/storage/brand.png",
            is_active=False,
        )
        db.add(brand)
        db.commit()
        brand_id = int(brand.id)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from brands " in normalized:
            statements.append(normalized)

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get("/api/brands", headers=auth_headers)
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    brand_row = next(row for row in response.json() if row["id"] == brand_id)
    assert brand_row == {
        "id": brand_id,
        "name": name,
        "description": "projected description",
        "logo_url": "/storage/brand.png",
        "is_active": False,
    }
    assert len(statements) == 1
    selected = statements[0].split(" from brands", 1)[0]
    for column in ("id", "name", "description", "logo_url", "is_active"):
        assert f"brands.{column}" in selected
    assert "brands.created_at" not in selected
    assert "brands.updated_at" not in selected
