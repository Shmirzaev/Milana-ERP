from sqlalchemy import event

from app.api.routes.catalog import _model_usage_blockers
from app.tests.conftest import TestSessionLocal


def test_model_usage_blocker_checks_select_only_primary_keys():
    tables = (
        "sales_order_items",
        "production_orders",
        "production_order_items",
        "bundles",
        "packages",
        "package_items",
        "finished_goods_stock",
    )
    with TestSessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and any(f" from {table} " in normalized for table in tables):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            assert _model_usage_blockers(db, 2_147_483_000) == []
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == len(tables), statements
    for table, statement in zip(tables, statements, strict=True):
        assert f"select {table}.id " in statement
        assert f" from {table} " in statement
