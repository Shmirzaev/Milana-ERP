from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Department, Model, ProductionOrder, WorkOrder
from app.services.production import create_work_orders


def test_work_order_generation_reads_existing_operations_as_scalar_columns():
    marker = uuid4().hex[:8].upper()
    statements = []
    with SessionLocal() as db:
        model = Model(code=f"WO-PROJECTION-{marker}", name="Work-order projection", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"WO-PROJECTION-{marker}",
            production_type="branded_stock",
            source_type="standard",
            model_id=model.id,
            planned_quantity=12,
        )
        db.add(order)
        db.flush()
        cutting = db.query(Department).filter(Department.code == "CUT").first()
        db.add(WorkOrder(
            production_order_id=order.id,
            department_id=cutting.id,
            operation="cutting",
            status="completed",
            planned_input_qty=12,
            planned_output_qty=12,
        ))
        db.commit()
        order_id = order.id
        legacy_sql = str(
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == order_id)
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        bind = db.get_bind()

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        with SessionLocal() as db:
            created = create_work_orders(db, order_id, include_storage_transfer=False)
            assert {row.operation for row in created} == {"sewing", "packaging"}
            db.commit()
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    existing_ops_read = next(
        statement for statement in statements
        if " from work_orders " in statement
        and "work_orders.production_order_id =" in statement
        and "work_orders.operation" in statement
    )
    assert "select work_orders.operation " in existing_ops_read
    assert "work_orders.notes" not in existing_ops_read
    assert "work_orders.block_reason" not in existing_ops_read
    assert "work_orders.notes" in legacy_sql
    assert "work_orders.block_reason" in legacy_sql
