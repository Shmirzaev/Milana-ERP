from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Department,
    Model,
    PackagingRecord,
    PrintingRecord,
    ProductionBatch,
    ProductionOrder,
    SewingRecord,
    WorkOrder,
)
from app.services.traceability import (
    _work_orders_for_po,
    build_traceability,
    production_batch_traceability,
)


def _select_trace(db, callback):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _work_order_case(db, work_order_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    order = ProductionOrder(
        production_no=f"PERF21-WO-PO-{suffix}",
        production_type="branded_stock",
        model_id=model_id,
        status="printing",
        planned_quantity=1,
    )
    db.add(order)
    db.flush()
    batches = [
        ProductionBatch(
            production_order_id=order.id,
            batch_no=f"PERF21-WO-B-{suffix}-{number:04d}",
            batch_index=number + 1,
            planned_quantity=1,
        )
        for number in range(work_order_count)
    ]
    db.add_all(batches)
    db.flush()
    work_orders = [
        WorkOrder(
            production_order_id=order.id,
            production_batch_id=batch.id,
            department_id=department_id,
            operation="printing",
            status="waiting",
            planned_input_qty=1,
            planned_output_qty=1,
        )
        for batch in batches
    ]
    db.add_all(work_orders)
    db.commit()
    return {
        "order_id": order.id,
        "target_batch_id": batches[0].id,
        "batch_ids": [batch.id for batch in batches],
        "work_order_ids": [work_order.id for work_order in work_orders],
    }


@pytest.mark.parametrize("work_order_count", [1, 50, 401])
def test_production_batch_graph_reuses_single_ordered_work_order_load(work_order_count):
    with SessionLocal() as db:
        case = _work_order_case(db, work_order_count)

    with SessionLocal() as db:
        batch = db.get(ProductionBatch, case["target_batch_id"])
        payload, statements = _select_trace(
            db,
            lambda: production_batch_traceability(db, batch),
        )

    work_order_queries = [statement for statement in statements if " from work_orders " in statement]
    assert len(work_order_queries) == 1, statements
    assert [row["operation"] for row in payload["stage_summary"]] == [
        "cutting",
        "printing",
        "sewing",
        "packaging",
        "storage_transfer",
        "shipment",
    ]
    assert payload["production_batch"]["id"] == case["target_batch_id"]


def test_preloaded_work_orders_preserve_base_graph_response_and_order():
    with SessionLocal() as db:
        case = _work_order_case(db, 3)

    with SessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        scalar = build_traceability(
            db,
            subject_type="production_batch",
            production_order=order,
            production_batch_id=case["target_batch_id"],
        )

    with SessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        work_orders = _work_orders_for_po(db, case["order_id"])
        assert [work_order.id for work_order in work_orders] == case["work_order_ids"]
        preloaded = build_traceability(
            db,
            subject_type="production_batch",
            production_order=order,
            production_batch_id=case["target_batch_id"],
            preloaded_work_orders=work_orders,
        )

    scalar.pop("generated_at")
    preloaded.pop("generated_at")
    assert preloaded == scalar


def test_traceability_work_order_lookup_projects_only_consumed_fields():
    with SessionLocal() as db:
        case = _work_order_case(db, 2)
        legacy_sql = str(
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == case["order_id"])
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        work_orders, statements = _select_trace(
            db,
            lambda: _work_orders_for_po(db, case["order_id"]),
        )

    assert [row.id for row in work_orders] == case["work_order_ids"]
    assert {row.operation for row in work_orders} == {"printing"}
    assert {row.production_batch_id for row in work_orders} == set(case["batch_ids"])
    work_order_read = next(statement for statement in statements if " from work_orders " in statement)
    assert "work_orders.id" in work_order_read
    assert "work_orders.production_batch_id" in work_order_read
    assert "work_orders.operation" in work_order_read
    assert "work_orders.notes" not in work_order_read
    assert "work_orders.actual_input_qty" not in work_order_read
    assert "work_orders.notes" in legacy_sql
    assert "work_orders.actual_input_qty" in legacy_sql


def test_traceability_operation_records_project_only_payload_fields():
    with SessionLocal() as db:
        case = _work_order_case(db, 1)
        work_order_id = case["work_order_ids"][0]
        db.add_all(
            [
                PrintingRecord(work_order_id=work_order_id, input_qty=12, printed_qty=11, notes="print"),
                SewingRecord(work_order_id=work_order_id, input_qty=11, sewn_qty=10, notes="sew"),
                PackagingRecord(work_order_id=work_order_id, input_qty=10, packed_qty=9, notes="pack"),
            ]
        )
        db.commit()

    with SessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        payload, statements = _select_trace(
            db,
            lambda: build_traceability(db, subject_type="production_order", production_order=order),
        )

    record_selects = {
        table: next(statement for statement in statements if f" from {table} " in statement)
        for table in ("printing_records", "sewing_records", "packaging_records")
    }
    assert "printing_records.input_qty" in record_selects["printing_records"]
    assert "printing_records.notes" in record_selects["printing_records"]
    assert "sewing_records.line_name" in record_selects["sewing_records"]
    assert "sewing_records.size_quantities" not in record_selects["sewing_records"]
    assert "packaging_records.packaging_material_used" in record_selects["packaging_records"]
    assert "packaging_records.notes" in record_selects["packaging_records"]
    assert payload["printing_records"][0]["notes"] == "print"
    assert payload["sewing_records"][0]["notes"] == "sew"
    assert payload["packaging_records"][0]["notes"] == "pack"
