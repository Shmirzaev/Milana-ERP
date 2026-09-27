from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.partners import list_customers
from app.models import Customer


def test_customer_list_counts_scalar_and_projects_party_fields_without_deferred_reads():
    engine = create_engine("sqlite://")
    Customer.__table__.create(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    Customer(name="Projection customer 1", phone="111", notes="note 1"),
                    Customer(name="Projection customer 2", email="two@example.com", address="Address 2"),
                ]
            )
            db.commit()

            statements = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(" ".join(statement.lower().split()))

            event.listen(engine, "before_cursor_execute", capture)
            try:
                payload = list_customers(db, object(), q="Projection customer", page=1, page_size=10)
            finally:
                event.remove(engine, "before_cursor_execute", capture)

        assert payload["total"] == 2
        assert [row["name"] for row in payload["rows"]] == ["Projection customer 2", "Projection customer 1"]
        assert payload["rows"][0]["email"] == "two@example.com"
        assert payload["rows"][1]["notes"] == "note 1"
        count_queries = [statement for statement in statements if "count(" in statement]
        assert len(count_queries) == 1, statements
        assert "count(customers.id)" in count_queries[0]
        assert " from (select customers." not in count_queries[0]
        row_queries = [statement for statement in statements if " from customers " in statement and "count(" not in statement]
        assert len(row_queries) == 1, statements
        selected_columns = row_queries[0].split(" from customers ", 1)[0]
        assert "customers.name" in selected_columns
        assert "customers.notes" in selected_columns
        assert "customers.created_at" not in selected_columns
        assert "customers.is_active" not in selected_columns
    finally:
        engine.dispose()
