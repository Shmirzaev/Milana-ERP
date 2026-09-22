from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Department, Model, ProductionBatch, ProductionOrder, WorkOrder
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
