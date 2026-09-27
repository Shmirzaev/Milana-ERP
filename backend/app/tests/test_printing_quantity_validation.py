from uuid import uuid4

import pytest

from app.models import (
    AuditLog,
    CuttingRecord,
    Department,
    FinishedGoodsStock,
    Notification,
    PayrollRecord,
    PrintingRecord,
    ProductionBatch,
    ProductionOrder,
    SewingAssignment,
    StockBatch,
    StockMovement,
    WasteRecord,
    WorkOrder,
)
from app.schemas.production import PrintingRecordIn
from app.tests.conftest import TestSessionLocal


def _printing_scope() -> tuple[int, int, int, int]:
    with TestSessionLocal.begin() as db:
        departments = {
            row.code: row.id
            for row in db.query(Department).filter(Department.code.in_(("CUT", "PRT", "SEW"))).all()
        }
        order = ProductionOrder(
            production_no=f"WF04-{uuid4().hex}",
            production_type="branded_stock",
            model_id=1,
            status="printing",
            planned_quantity=10,
            created_by=1,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no="001",
            batch_index=1,
            name="WF04",
            planned_quantity=10,
        )
        db.add(batch)
        db.flush()
        cutting = WorkOrder(
            production_order_id=order.id,
            department_id=departments["CUT"],
            operation="cutting",
            status="completed",
            planned_input_qty=10,
            planned_output_qty=10,
            actual_input_qty=10,
            actual_output_qty=10,
            passed_qty=10,
        )
        printing = WorkOrder(
            production_order_id=order.id,
            department_id=departments["PRT"],
            operation="printing",
            status="collected",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        sewing = WorkOrder(
            production_order_id=order.id,
            department_id=departments["SEW"],
            operation="sewing",
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        db.add_all((cutting, printing, sewing))
        db.flush()
        db.add(CuttingRecord(
            work_order_id=cutting.id,
            production_batch_id=batch.id,
            input_quantity=1,
            input_unit="kg",
            cut_pieces=10,
            passed_pieces=10,
            defective_pieces=0,
            waste_quantity=0,
            waste_unit="kg",
            approval_status="approved",
        ))
        return order.id, batch.id, printing.id, sewing.id


def _write_state(order_id: int) -> dict:
    with TestSessionLocal() as db:
        work_orders = db.query(WorkOrder).filter_by(production_order_id=order_id).order_by(WorkOrder.id).all()
        return {
            "work_orders": [
                (
                    row.id,
                    row.status,
                    row.actual_input_qty,
                    row.actual_output_qty,
                    row.passed_qty,
                    row.failed_qty,
                    row.rework_qty,
                    row.start_time,
                    row.end_time,
                )
                for row in work_orders
            ],
            "printing_records": db.query(PrintingRecord).count(),
            "waste_records": db.query(WasteRecord).count(),
            "audit_logs": db.query(AuditLog).count(),
            "notifications": db.query(Notification).count(),
            "stock_movements": db.query(StockMovement).count(),
            "stock_batches": [
                (row.id, row.quantity, row.piece_count)
                for row in db.query(StockBatch).order_by(StockBatch.id).all()
            ],
            "finished_goods": [
                (row.id, row.quantity, row.available_qty, row.reserved_qty, row.sold_qty)
                for row in db.query(FinishedGoodsStock).order_by(FinishedGoodsStock.id).all()
            ],
            "payroll": [
                (row.id, row.quantity, row.total_amount, row.status)
                for row in db.query(PayrollRecord).order_by(PayrollRecord.id).all()
            ],
            "assignments": [
                (row.id, row.quantity, row.completed_qty, row.status)
                for row in db.query(SewingAssignment).order_by(SewingAssignment.id).all()
            ],
        }


def test_printing_rejects_output_above_verified_input_without_side_effects(client, auth_headers):
    order_id, batch_id, printing_id, _ = _printing_scope()
    before = _write_state(order_id)

    response = client.post(
        "/api/printing/records",
        headers=auth_headers,
        json={
            "work_order_id": printing_id,
            "production_batch_id": batch_id,
            "input_qty": 10,
            "printed_qty": 10,
            "passed_qty": 11,
            "rejected_qty": 0,
        },
    )

    assert response.status_code == 422, response.text
    assert _write_state(order_id) == before


@pytest.mark.parametrize(
    "quantities",
    [
        {"input_qty": -1, "printed_qty": 0, "passed_qty": 0},
        {"input_qty": 1, "printed_qty": -1, "passed_qty": 0},
        {"input_qty": 1, "printed_qty": 1, "passed_qty": -1},
        {"input_qty": 1, "printed_qty": 1, "passed_qty": 1, "rejected_qty": -1},
        {"input_qty": 2**31, "printed_qty": 0, "passed_qty": 0},
        {"input_qty": 1, "printed_qty": 2**31, "passed_qty": 0},
        {"input_qty": 1, "printed_qty": 1, "passed_qty": 2**31},
        {"input_qty": 1, "printed_qty": 1, "passed_qty": 1, "rejected_qty": 2**31},
        {"input_qty": 10, "printed_qty": 11, "passed_qty": 10},
        {"input_qty": 10, "printed_qty": 10, "passed_qty": 11},
        {"input_qty": 10, "printed_qty": 10, "passed_qty": 10, "rejected_qty": 1},
    ],
)
def test_printing_schema_rejects_invalid_quantities(quantities):
    with pytest.raises(ValueError):
        PrintingRecordIn(work_order_id=1, **quantities)


@pytest.mark.parametrize(
    ("input_qty", "printed_qty", "passed_qty", "rejected_qty"),
    [(10, 8, 7, 1), (10, 5, 5, 5), (0, 0, 0, 0)],
)
def test_printing_accepts_partial_rejection_shortage_and_existing_zero_record(
    client,
    auth_headers,
    input_qty,
    printed_qty,
    passed_qty,
    rejected_qty,
):
    _, batch_id, printing_id, sewing_id = _printing_scope()
    with TestSessionLocal() as db:
        stock_before = db.query(StockMovement).count()
        payroll_before = db.query(PayrollRecord).count()
        assignments_before = db.query(SewingAssignment).count()

    response = client.post(
        "/api/printing/records",
        headers=auth_headers,
        json={
            "work_order_id": printing_id,
            "production_batch_id": batch_id,
            "input_qty": input_qty,
            "printed_qty": printed_qty,
            "passed_qty": passed_qty,
            "rejected_qty": rejected_qty,
        },
    )

    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        record = db.query(PrintingRecord).filter_by(work_order_id=printing_id).one()
        assert (record.input_qty, record.printed_qty, record.passed_qty, record.rejected_qty) == (
            input_qty,
            printed_qty,
            passed_qty,
            rejected_qty,
        )
        printing = db.get(WorkOrder, printing_id)
        assert (
            printing.actual_input_qty,
            printing.actual_output_qty,
            printing.passed_qty,
            printing.failed_qty,
        ) == (input_qty, passed_qty, passed_qty, rejected_qty)
        sewing = db.get(WorkOrder, sewing_id)
        assert (sewing.actual_input_qty, sewing.actual_output_qty, sewing.passed_qty, sewing.failed_qty) == (0, 0, 0, 0)
        assert db.query(StockMovement).count() == stock_before
        assert db.query(PayrollRecord).count() == payroll_before
        assert db.query(SewingAssignment).count() == assignments_before
