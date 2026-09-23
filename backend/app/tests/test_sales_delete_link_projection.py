from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.sales import delete_sales_order
from app.models import Model, ProductionOrder, SalesOrder
from app.tests.conftest import TestSessionLocal


def test_sales_order_delete_production_link_check_selects_only_id():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        model = Model(
            code=f"DELETE-LINK-{marker}",
            name=f"Delete link model {marker}",
            category="T-shirt",
            product_type="shirt",
            status="approved",
        )
        order = SalesOrder(
            order_no=f"DELETE-LINK-SO-{marker}",
            status="draft",
            total_amount=0,
        )
        db.add_all([model, order])
        db.flush()
        production_order = ProductionOrder(
            production_no=f"DELETE-LINK-PO-{marker}",
            production_type="client_order",
            model_id=model.id,
            sales_order_id=order.id,
            planned_quantity=1,
            status="new",
        )
        db.add(production_order)
        db.commit()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from production_orders " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            with pytest.raises(HTTPException) as error:
                delete_sales_order(order.id, db, SimpleNamespace())
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert db.get(SalesOrder, order.id) is not None

    assert error.value.status_code == 409
    assert error.value.detail == "Sales order already has linked production orders"
    assert len(statements) == 1, statements
    assert "select production_orders.id " in statements[0]
    assert "production_orders.production_no" not in statements[0]
