from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Department, Model, ProductionOrder, QualityCheck, WorkOrder
from app.services.traceability import build_traceability


def test_traceability_quality_checks_select_only_response_columns():
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        department_id = db.query(Department.id).order_by(Department.id).first()[0]
        order = ProductionOrder(
            production_no=f"TRACE-QC-{marker}",
            production_type="branded_stock",
            model_id=model_id,
            status="cutting",
            planned_quantity=4,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation="quality",
            status="completed",
            planned_input_qty=4,
            planned_output_qty=4,
        )
        db.add(work_order)
        db.flush()
        db.add(
            QualityCheck(
                work_order_id=work_order.id,
                department_id=department_id,
                checked_qty=4,
                passed_qty=3,
                failed_qty=1,
                defect_type="stitch",
                defect_reason="loose seam",
                severity="medium",
            )
        )
        db.commit()
        order_id = int(order.id)

    with SessionLocal() as db:
        order = db.get(ProductionOrder, order_id)
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "quality_checks" in statement.lower():
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = build_traceability(
                db,
                subject_type="production_order",
                production_order=order,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result["quality_checks"] == [
        {
            "id": result["quality_checks"][0]["id"],
            "work_order_id": result["quality_checks"][0]["work_order_id"],
            "department_id": result["quality_checks"][0]["department_id"],
            "checked_qty": 4,
            "passed_qty": 3,
            "failed_qty": 1,
            "defect_type": "stitch",
            "defect_reason": "loose seam",
            "severity": "medium",
            "checked_by": None,
            "checked_at": None,
        }
    ]
    assert len(statements) == 1
    selected = statements[0].split(" from quality_checks", 1)[0]
    assert "quality_checks.checked_qty" in selected
    assert "quality_checks.defect_reason" in selected
    assert "quality_checks.created_at" not in selected
