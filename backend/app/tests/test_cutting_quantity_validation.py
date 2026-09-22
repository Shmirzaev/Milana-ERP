from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.production import _parse_cutting_bundle_specs
from app.models import (
    AuditLog,
    Bundle,
    CuttingRecord,
    Department,
    Notification,
    ProductionOrder,
    WasteRecord,
    WorkOrder,
)
from app.schemas.production import CuttingRecordIn
from app.tests.conftest import TestSessionLocal


def _cutting_scope() -> tuple[int, int]:
    with TestSessionLocal.begin() as db:
        cutting_department = db.query(Department).filter_by(code="CUT").one()
        order = ProductionOrder(
            production_no=f"WF04-CUT-{uuid4().hex}",
            production_type="branded_stock",
            model_id=1,
            status="cutting",
            planned_quantity=10,
            created_by=1,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=cutting_department.id,
            operation="cutting",
            status="in_progress",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        db.add(work_order)
        db.flush()
        return order.id, work_order.id


def _write_state(order_id: int, work_order_id: int) -> dict:
    with TestSessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        return {
            "work_order": (
                work_order.status,
                work_order.actual_input_qty,
                work_order.actual_output_qty,
                work_order.passed_qty,
                work_order.failed_qty,
                work_order.start_time,
                work_order.end_time,
            ),
            "cutting_records": db.query(CuttingRecord).filter_by(work_order_id=work_order_id).count(),
            "bundles": db.query(Bundle).filter_by(production_order_id=order_id).count(),
            "waste_records": db.query(WasteRecord).filter_by(production_order_id=order_id).count(),
            "audit_logs": db.query(AuditLog).count(),
            "notifications": db.query(Notification).count(),
        }


def test_cutting_rejects_negative_quantity_without_side_effects(client, auth_headers):
    order_id, work_order_id = _cutting_scope()
    before = _write_state(order_id, work_order_id)

    response = client.post(
        "/api/cutting/records",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "input_quantity": 0,
            "cut_pieces": -1,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "bundles": [],
        },
    )

    assert response.status_code == 422, response.text
    assert _write_state(order_id, work_order_id) == before


@pytest.mark.parametrize(
    "quantities",
    [
        {"input_quantity": -1},
        {"input_quantity": float("nan")},
        {"cut_pieces": -1},
        {"report_piece_count": -1},
        {"passed_pieces": -1},
        {"defective_pieces": -1},
        {"waste_quantity": -1},
        {"waste_quantity": float("inf")},
        {"cut_pieces": 2**31},
        {"report_piece_count": 2**31},
        {"passed_pieces": 2**31},
        {"defective_pieces": 2**31},
        {"cut_pieces": 10, "passed_pieces": 10, "defective_pieces": 1},
    ],
)
def test_cutting_schema_rejects_invalid_quantities(quantities):
    payload = {
        "work_order_id": 1,
        "input_quantity": 0,
        "cut_pieces": 10,
        "passed_pieces": 10,
        "defective_pieces": 0,
        "waste_quantity": 0,
    }
    payload.update(quantities)

    with pytest.raises(ValueError):
        CuttingRecordIn(**payload)


def test_cutting_accepts_conserved_output_and_bundle_derived_output():
    conserved = CuttingRecordIn(
        work_order_id=1,
        input_quantity=0,
        cut_pieces=10,
        passed_pieces=7,
        defective_pieces=3,
    )
    assert conserved.passed_pieces == 7

    derived = CuttingRecordIn(
        work_order_id=1,
        input_quantity=0,
        cut_pieces=1,
        passed_pieces=0,
        bundles=[{"color": "white", "size": "M", "quantity": 10, "count": 1}],
    )
    assert derived.bundles[0]["quantity"] == 10

    with pytest.raises(ValueError):
        CuttingRecordIn(
            work_order_id=1,
            input_quantity=0,
            cut_pieces=1,
            passed_pieces=2,
            bundles=[{"color": "white", "size": "M", "quantity": 10, "count": 0}],
        )


def test_cutting_bundle_plan_rejects_int4_total():
    with pytest.raises(HTTPException, match="total quantity is too large"):
        _parse_cutting_bundle_specs([
            {"color": "white", "size": "M", "quantity": 2_147_483_647, "count": 1},
            {"color": "black", "size": "L", "quantity": 1, "count": 1},
        ])
