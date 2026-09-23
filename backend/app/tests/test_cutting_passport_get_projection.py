from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.cutting_passports import get_passport
from app.models import CuttingPassport, User
from app.tests.conftest import TestSessionLocal, test_engine


def test_single_passport_read_projects_joined_operator_and_order_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        operator = User(
            name=f"Passport operator {marker}",
            email=f"passport-{marker}@example.test",
            password_hash="unused-test-hash",
        )
        db.add(operator)
        db.flush()
        passport = CuttingPassport(
            passport_no=f"GET-PROJECTION-{marker}",
            date=datetime(2026, 9, 23, tzinfo=timezone.utc),
            operator_id=operator.id,
            operator_name_manual="Manual fallback",
        )
        db.add(passport)
        db.commit()
        passport_id = passport.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            payload = get_passport(passport_id, db, current=None)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert payload["passport_no"] == f"GET-PROJECTION-{marker}"
    assert payload["operator_name"] == f"Passport operator {marker}"
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from ", 1)[0]
    assert "users_1.name" in selected_columns
    assert "users_1.email" not in selected_columns
    assert "users_1.password_hash" not in selected_columns
    assert "production_orders_1.production_no" in selected_columns
    assert "production_orders_1.planned_quantity" not in selected_columns
    assert "sales_orders_1.order_no" in selected_columns
    assert "sales_orders_1.total_amount" not in selected_columns
