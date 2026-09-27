from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.production import (
    CuttingMaterialDetailsUpdateIn,
    CuttingRecordDetailsUpdateIn,
    _parse_cutting_bundle_specs,
)
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


@pytest.mark.parametrize(
    "field",
    ["input_quantity", "waste_quantity", "layer_material_kg", "beika_kg", "material_rolls_used"],
)
@pytest.mark.parametrize("value", ["10000000000", "Infinity", "-Infinity", "NaN"])
def test_cutting_numeric_storage_fields_reject_nonrepresentable_values(field, value):
    payload = {
        "work_order_id": 1,
        "input_quantity": 0,
        "cut_pieces": 0,
        "passed_pieces": 0,
        field: value,
    }

    with pytest.raises(ValueError):
        CuttingRecordIn(**payload)


def test_cutting_numeric_storage_fields_keep_roundable_float_contract():
    record = CuttingRecordIn(
        work_order_id=1,
        input_quantity="9999999999.9999",
        cut_pieces=0,
        passed_pieces=0,
        waste_quantity="1.234567",
    )

    assert record.input_quantity == 9999999999.9999
    assert record.waste_quantity == 1.234567


@pytest.mark.parametrize("schema,field", [
    (CuttingRecordDetailsUpdateIn, "layer_material_kg"),
    (CuttingRecordDetailsUpdateIn, "beika_kg"),
    (CuttingRecordDetailsUpdateIn, "material_rolls_used"),
    (CuttingMaterialDetailsUpdateIn, "layer_material_kg"),
    (CuttingMaterialDetailsUpdateIn, "beika_kg"),
    (CuttingMaterialDetailsUpdateIn, "material_rolls_used"),
])
@pytest.mark.parametrize("value", ["10000000000", "Infinity", "-Infinity", "NaN"])
def test_cutting_details_update_rejects_nonrepresentable_values(schema, field, value):
    payload = {field: value}
    if schema is CuttingMaterialDetailsUpdateIn:
        payload = {
            "stock_batch_id": 1,
            "layer_material_kg": 0,
            "beika_kg": 0,
            "material_rolls_used": 0,
            "layup_operator_name": "Operator",
            field: value,
        }

    with pytest.raises(ValueError):
        schema(**payload)


def test_cutting_record_details_update_preserves_route_negative_quantity_validation():
    payload = CuttingRecordDetailsUpdateIn(layer_material_kg=-1)

    assert payload.layer_material_kg == -1


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


@pytest.mark.parametrize(
    "spec, message",
    [
        ({"color": "white", "size": "M", "quantity": 1.5, "count": 1}, "whole numbers"),
        ({"color": "white", "size": "M", "quantity": 1, "count": True}, "whole numbers"),
        ({"color": "x" * 65, "size": "M", "quantity": 1, "count": 1}, "color.*64 characters"),
        ({"color": "white", "size": "x" * 33, "quantity": 1, "count": 1}, "size.*32 characters"),
    ],
)
def test_cutting_bundle_plan_rejects_invalid_embedded_shapes(spec, message):
    with pytest.raises(HTTPException, match=message):
        _parse_cutting_bundle_specs([spec])


def test_cutting_bundle_plan_caps_raw_rows_even_when_bundle_count_is_zero():
    rows = [
        {"color": "white", "size": "M", "quantity": 0, "count": 0}
        for _ in range(1001)
    ]

    with pytest.raises(HTTPException, match="cannot contain more than 1000 rows"):
        _parse_cutting_bundle_specs(rows)


@pytest.mark.parametrize(
    ("destination", "message"),
    [
        ({"next": "pakaging"}, "unsupported next stage"),
        ({"next": "sewing", "sewing_factory": "besttexx"}, "unsupported sewing factory"),
    ],
)
def test_cutting_bundle_plan_rejects_unknown_destination(destination, message):
    spec = {"color": "white", "size": "M", "quantity": 1, "count": 1, **destination}

    with pytest.raises(HTTPException, match=message):
        _parse_cutting_bundle_specs([spec])


def test_cutting_bundle_plan_preserves_supported_destination_aliases():
    parsed = _parse_cutting_bundle_specs([
        {"color": "white", "size": "M", "quantity": 1, "count": 1, "next": "printing", "sewing_factory": "besttex"},
        {"color": "white", "size": "L", "quantity": 1, "count": 1, "next": "BST"},
        {"color": "white", "size": "XL", "quantity": 1, "count": 1},
    ])

    assert [(row["next_code"], row["factory_code"]) for row in parsed] == [
        ("PRT", "BST"),
        ("BST", "BST"),
        ("MIL", "MIL"),
    ]


def test_cutting_bundle_unknown_destination_does_not_write_cutting_state(client, auth_headers):
    order_id, work_order_id = _cutting_scope()
    before = _write_state(order_id, work_order_id)
    payload = {
        "work_order_id": work_order_id,
        "input_quantity": 0,
        "cut_pieces": 0,
        "passed_pieces": 0,
        "defective_pieces": 0,
        "waste_quantity": 0,
        "bundles": [
            {"color": "white", "size": "M", "quantity": 1, "count": 1, "next": "pakaging"},
        ],
    }

    response = client.post("/api/cutting/records", headers=auth_headers, json=payload)

    assert response.status_code == 400, response.text
    assert "unsupported next stage" in response.json()["detail"]
    assert _write_state(order_id, work_order_id) == before
    assert client.post("/api/cutting/records", json=payload).status_code == 401


def test_cutting_bundle_shape_failure_does_not_write_cutting_state(client, auth_headers):
    order_id, work_order_id = _cutting_scope()
    before = _write_state(order_id, work_order_id)

    response = client.post(
        "/api/cutting/records",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "input_quantity": 0,
            "cut_pieces": 0,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "bundles": [
                {"color": "x" * 65, "size": "M", "quantity": 1, "count": 1},
            ],
        },
    )

    assert response.status_code == 400, response.text
    assert "color" in response.json()["detail"]
    assert _write_state(order_id, work_order_id) == before
