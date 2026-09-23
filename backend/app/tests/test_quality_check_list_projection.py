from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.production import list_quality
from app.models import Department, Model, ProductionOrder, QualityCheck, User, WorkOrder
from app.schemas.production import QualityCheckOut
from app.tests.conftest import TestSessionLocal, test_engine


def test_quality_check_page_counts_scalar_and_projects_response_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        department = db.query(Department).order_by(Department.id).first()
        model = db.query(Model).order_by(Model.id).first()
        admin = db.query(User).filter_by(email="admin@example.com").one()
        assert department is not None
        assert model is not None
        order = ProductionOrder(
            production_no=f"QUALITY-PROJECTION-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=5,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="cutting",
            status="waiting",
            planned_input_qty=5,
            planned_output_qty=5,
        )
        db.add(work_order)
        db.flush()
        quality_check = QualityCheck(
            work_order_id=work_order.id,
            department_id=department.id,
            checked_qty=5,
            passed_qty=4,
            failed_qty=1,
            defect_type="seam",
            defect_reason="Skipped stitch",
            severity="medium",
            checked_by=admin.id,
            checked_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        db.add(quality_check)
        db.commit()
        work_order_id = work_order.id
        quality_check_id = quality_check.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            payload = list_quality(db, _=None, work_order_id=work_order_id, page=1, page_size=10)
            rows = [QualityCheckOut.model_validate(row) for row in payload["rows"]]
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert payload["total"] == 1
    assert len(rows) == 1
    assert rows[0].id == quality_check_id
    assert rows[0].checked_qty == 5
    assert rows[0].passed_qty == 4
    assert rows[0].failed_qty == 1
    assert rows[0].severity == "medium"
    count_queries = [statement for statement in statements if "count(" in statement]
    assert len(count_queries) == 1, statements
    assert "count(quality_checks.id)" in count_queries[0]
    assert " from (select quality_checks." not in count_queries[0]
    row_queries = [statement for statement in statements if " from quality_checks " in statement and "count(" not in statement]
    assert len(row_queries) == 1, statements
    selected_columns = row_queries[0].split(" from quality_checks ", 1)[0]
    assert "quality_checks.checked_qty" in selected_columns
    assert "quality_checks.checked_by" not in selected_columns
