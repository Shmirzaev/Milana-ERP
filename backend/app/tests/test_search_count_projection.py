from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Customer


def test_paginated_search_counts_id_only_union_without_display_join(client, auth_headers):
    marker = f"COUNT-PROJECTION-{uuid4().hex[:12]}"
    with SessionLocal() as db:
        customer = Customer(name=marker)
        db.add(customer)
        db.commit()
        customer_id = customer.id

    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()).lower())

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/search",
            params={"q": marker, "page": 1, "page_size": 10},
            headers=auth_headers,
        )
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)
        with SessionLocal() as db:
            db.query(Customer).filter(Customer.id == customer_id).delete()
            db.commit()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["rows"] == [
        {
            "type": "Customer",
            "id": customer_id,
            "label": marker,
            "url": f"/customers?q={marker}",
        }
    ]

    count_sql = next(statement for statement in statements if "count(*)" in statement)
    assert "customers.id as id" in count_sql
    assert "customers.name as value1" not in count_sql
    assert "left outer join customers" not in count_sql
