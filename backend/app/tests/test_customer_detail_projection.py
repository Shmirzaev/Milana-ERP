from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.partners import get_customer
from app.models import Customer
from app.schemas.catalog import PartyOut
from app.tests.conftest import TestSessionLocal, test_engine


def test_customer_detail_selects_only_party_response_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        customer = Customer(
            name=f"Projected customer {marker}",
            phone="+998900000001",
            email=f"customer-{marker}@example.test",
            address="Customer address",
            notes="Customer notes",
        )
        db.add(customer)
        db.commit()
        customer_id = customer.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            result = PartyOut.model_validate(get_customer(customer_id, db, _=None))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert result.id == customer_id
    assert result.name == f"Projected customer {marker}"
    assert result.email == f"customer-{marker}@example.test"
    assert result.notes == "Customer notes"
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from customers ", 1)[0]
    for field in ("id", "name", "phone", "email", "address", "notes"):
        assert f"customers.{field}" in selected_columns
    for field in ("created_at", "updated_at"):
        assert f"customers.{field}" not in selected_columns

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_customer(customer_id + 1_000_000_000, db, _=None)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Customer not found"
