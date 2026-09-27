from uuid import uuid4

from sqlalchemy import event

from app.api.routes.usluga import _structural_edit_blocker
from app.models import Department, Model, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def test_usluga_structural_blocker_projects_only_work_order_evidence():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(
            code=f"USLUGA-BLOCK-{marker}",
            name=f"Blocker projection {marker}",
            category="T-shirt",
            product_type="shirt",
            status="approved",
        )
        department = Department(
            code=f"UB{marker[:3]}",
            name=f"Blocker department {marker}",
        )
        db.add_all([model, department])
        db.flush()
        order = ProductionOrder(
            production_no=f"USLUGA-BLOCK-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
            status="planning",
        )
        db.add(order)
        db.flush()
        db.add(
            WorkOrder(
                production_order_id=order.id,
                department_id=department.id,
                operation="cutting",
                status="waiting",
                planned_input_qty=10,
                planned_output_qty=10,
            )
        )
        db.flush()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from work_orders " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            assert _structural_edit_blocker(db, order) is None
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == 1, statements
    for selected in (
        "work_orders.id",
        "work_orders.actual_input_qty",
        "work_orders.actual_output_qty",
        "work_orders.passed_qty",
        "work_orders.failed_qty",
        "work_orders.rework_qty",
        "work_orders.end_time",
        "work_orders.status",
    ):
        assert selected in statements[0]
    assert "work_orders.notes" not in statements[0]
    assert "work_orders.planned_input_qty" not in statements[0]
