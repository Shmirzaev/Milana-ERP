from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.partners import get_supplier
from app.models import Supplier
from app.schemas.catalog import PartyOut
from app.tests.conftest import TestSessionLocal, test_engine


def test_supplier_detail_selects_only_party_response_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        supplier = Supplier(
            name=f"Projected supplier {marker}",
            phone="+998900000001",
            email=f"supplier-{marker}@example.test",
            address="Supplier address",
            notes="Supplier notes",
            is_active=False,
        )
        db.add(supplier)
        db.commit()
        supplier_id = supplier.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            result = PartyOut.model_validate(get_supplier(supplier_id, db, _=None))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert result.id == supplier_id
    assert result.name == f"Projected supplier {marker}"
    assert result.email == f"supplier-{marker}@example.test"
    assert result.notes == "Supplier notes"
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from suppliers ", 1)[0]
    for field in ("id", "name", "phone", "email", "address", "notes"):
        assert f"suppliers.{field}" in selected_columns
    for field in ("is_active", "created_at", "updated_at"):
        assert f"suppliers.{field}" not in selected_columns

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_supplier(supplier_id + 1_000_000_000, db, _=None)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Supplier not found"
