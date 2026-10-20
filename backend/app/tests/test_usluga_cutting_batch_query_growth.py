from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import production
from app.db.session import SessionLocal
from app.models import (
    Bundle,
    CuttingRecord,
    Department,
    Model,
    ProductionBatch,
    ProductionOrder,
    SewingRecord,
    WorkOrder,
)


def _eco_user():
    return SimpleNamespace(
        role=SimpleNamespace(name=""),
        extra_permissions=[],
        factory_code="ECO",
        session_factory_code="ECO",
    )


def _select_trace(db, call):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _cutting_batch_set(db, count):
    suffix = uuid4().hex[:8]
    model_id = db.query(Model.id).order_by(Model.id).scalar()
    department_id = db.query(Department.id).filter(Department.code == "ECT").scalar()
    order = ProductionOrder(
        production_no=f"PERF20-PO-{suffix}",
        production_type="service_order",
        source_type="usluga",
        model_id=model_id,
        planned_quantity=count,
    )
    db.add(order)
    db.flush()
    work_order = WorkOrder(
        production_order_id=order.id,
        department_id=department_id,
        operation="cutting",
        planned_input_qty=count,
        planned_output_qty=count,
    )
    db.add(work_order)
    db.flush()
    batches = [
        ProductionBatch(
            production_order_id=order.id,
            batch_no=f"PERF20-BATCH-{suffix}-{number:04d}",
            batch_index=number + 1,
            planned_quantity=1,
        )
        for number in range(count)
    ]
    db.add_all(batches)
    db.flush()
    records = [
        CuttingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
            cutting_batch_no=f"PERF20-CUT-{suffix}-{number:04d}",
            material_name_snapshot="Customer fabric",
            material_role="main",
            approval_status="pending",
            input_quantity=1,
            cut_pieces=1,
            passed_pieces=1,
            bundle_count=1,
            total_bundled_quantity=1,
        )
        for number, batch in enumerate(batches)
    ]
    db.add_all(records)
    db.flush()
    db.add_all([
        Bundle(
            bundle_no=f"PERF20-BUNDLE-{suffix}-{number:04d}",
            barcode=f"PERF20-BC-{suffix}-{number:04d}",
            production_order_id=order.id,
            production_batch_id=batch.id,
            cutting_record_id=record.id,
            model_id=model_id,
            color="Natural",
            size="M",
            quantity=1,
            sewing_factory_code="ECO",
        )
        for number, (batch, record) in enumerate(zip(batches, records))
    ])
    db.commit()
    return work_order.id, [record.id for record in records]


@pytest.mark.parametrize(("record_count", "expected_selects"), [(1, 9), (50, 9), (401, 11)])
def test_usluga_cutting_batch_list_query_count_is_chunk_bounded(record_count, expected_selects):
    with SessionLocal() as db:
        work_order_id, record_ids = _cutting_batch_set(db, record_count)
    with SessionLocal() as db:
        payload, statements = _select_trace(
            db,
            lambda: production.list_usluga_cutting_batches(work_order_id, db, _eco_user()),
        )

    assert len(statements) == expected_selects
    assert [row["id"] for row in payload["items"]] == record_ids
    assert all(row["production_batch_no"].startswith("PERF20-BATCH-") for row in payload["items"])
    assert all(row["bundle_count"] == 1 for row in payload["items"])
    assert all(row["size_counts"] == [{"color": "Natural", "size": "M", "quantity": 1, "bundle_count": 1}]
               for row in payload["items"])


@pytest.mark.parametrize("batch_count", [1, 50])
@pytest.mark.parametrize("legacy", [False, True])
def test_cutting_progress_guards_share_existing_query_budget(batch_count, legacy):
    with SessionLocal() as db:
        work_id, _ = _cutting_batch_set(db, batch_count)
        work = db.get(WorkOrder, work_id)
        batches = db.query(ProductionBatch).filter_by(
            production_order_id=work.production_order_id,
        ).order_by(ProductionBatch.batch_index).all()
        target_id = batches[0].id
        sewing = WorkOrder(
            production_order_id=work.production_order_id,
            department_id=work.department_id,
            operation="sewing",
        )
        db.add(sewing)
        db.flush()
        db.add(SewingRecord(
            work_order_id=sewing.id,
            production_batch_id=None if legacy else target_id,
            input_qty=1, sewn_qty=1, passed_qty=1,
        ))
        # Output must still freeze a batch whose bundles are no longer present.
        db.query(Bundle).filter_by(production_batch_id=target_id).delete()
        db.commit()
    with SessionLocal() as db:
        payload, statements = _select_trace(
            db, lambda: production.cutting_batch_progress(work_id, db, _eco_user()),
        )
    # Work order, order + selectin materials, batches, totals, combined evidence.
    assert len(statements) == 6
    assert len(payload["items"]) == batch_count
    for row in payload["items"]:
        locked = legacy or row["id"] == target_id
        assert row["sewing_output_recorded"] is locked
        assert row["deletable"] is not locked
        assert row["name_editable"] is not locked
        assert row["bundle_count"] == (0 if row["id"] == target_id else 1)
