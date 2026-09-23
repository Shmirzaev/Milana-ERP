from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, WorkOrder
from app.services.traceability import build_traceability


def test_batch_traceability_filters_cutting_rows_in_sql_and_preserves_payload():
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        department_id = db.query(Department.id).order_by(Department.id).first()[0]
        order = ProductionOrder(
            production_no=f"PERF35-TRACE-{marker}",
            production_type="branded_stock",
            model_id=model_id,
            status="cutting",
            planned_quantity=20,
        )
        db.add(order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=f"PERF35-TRACE-B-{marker}-{index:03d}",
                batch_index=index + 1,
                planned_quantity=1,
            )
            for index in range(50)
        ]
        db.add_all(batches)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                production_batch_id=batch.id,
                department_id=department_id,
                operation="cutting",
                status="waiting",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            for batch in batches
        ]
        db.add_all(work_orders)
        db.flush()
        records = [
            CuttingRecord(
                work_order_id=work_order.id,
                production_batch_id=batch.id,
                input_quantity=1,
                input_unit="kg",
                cut_pieces=1,
                passed_pieces=1,
            )
            for batch, work_order in zip(batches, work_orders, strict=True)
        ]
        db.add_all(records)
        db.commit()
        order_id = int(order.id)
        target_batch_id = int(batches[0].id)
        target_record_id = int(records[0].id)

    with SessionLocal() as db:
        order = db.get(ProductionOrder, order_id)
        work_orders = (
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == order_id)
            .order_by(WorkOrder.id.asc())
            .all()
        )
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = build_traceability(
                db,
                subject_type="production_batch",
                production_order=order,
                production_batch_id=target_batch_id,
                preloaded_work_orders=work_orders,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    cutting_reads = [statement for statement in statements if " from cutting_records " in statement]
    assert len(cutting_reads) == 1
    assert "cutting_records.production_batch_id in (?)" in cutting_reads[0]
    assert [row["id"] for row in payload["cutting_records"]] == [target_record_id]
