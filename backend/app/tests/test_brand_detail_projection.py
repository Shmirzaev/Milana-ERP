from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.catalog import get_brand
from app.models import Brand
from app.schemas.catalog import BrandOut
from app.tests.conftest import TestSessionLocal, test_engine


def test_brand_detail_selects_only_brand_response_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        brand = Brand(
            name=f"Projected brand {marker}",
            description="Brand description",
            logo_url=f"/storage/brands/{marker}.webp",
            is_active=False,
        )
        db.add(brand)
        db.commit()
        brand_id = brand.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            result = BrandOut.model_validate(get_brand(brand_id, db, _=None))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert result.id == brand_id
    assert result.name == f"Projected brand {marker}"
    assert result.description == "Brand description"
    assert result.logo_url == f"/storage/brands/{marker}.webp"
    assert result.is_active is False
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from brands ", 1)[0]
    for field in ("id", "name", "description", "logo_url", "is_active"):
        assert f"brands.{field}" in selected_columns
    for field in ("created_at", "updated_at"):
        assert f"brands.{field}" not in selected_columns

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_brand(brand_id + 1_000_000_000, db, _=None)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Brand not found"
