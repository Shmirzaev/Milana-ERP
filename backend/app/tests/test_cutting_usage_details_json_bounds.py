from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import production
from app.db.session import SessionLocal
from app.models import (
    AuditLog, Bundle, CuttingMaterialUsage, CuttingRecord, Department, Item,
    MaterialReservation, ProductionOrder, StockBatch, StockMovement, Warehouse, WorkOrder,
)
from app.schemas.production import CuttingRecordIn


def _cutting_create_state() -> tuple[int, ...]:
    with SessionLocal() as db:
        return tuple(db.query(model).count() for model in (
            CuttingRecord, CuttingMaterialUsage, Bundle, MaterialReservation,
            StockMovement, AuditLog,
        ))


def test_cutting_create_rejects_unbounded_json_cut_pieces_before_writes(client, auth_headers):
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        warehouse = Warehouse(name=f"Cutting JSON {marker}", type="fabric_storage")
        item = Item(sku=f"CUT-JSON-{marker}", name=f"Cutting JSON {marker}", category="fabric", unit="kg")
        order = ProductionOrder(
            production_no=f"CUT-JSON-{marker}", production_type="branded_stock",
            model_id=1, status="cutting", planned_quantity=10, created_by=1,
        )
        db.add_all([warehouse, item, order])
        db.flush()
        batch = StockBatch(
            item_id=item.id, batch_no=marker, warehouse_id=warehouse.id,
            quantity=10, unit="kg", qc_status="passed",
        )
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter_by(code="CUT").scalar(),
            operation="cutting", status="in_progress",
            planned_input_qty=10, planned_output_qty=10,
        )
        db.add_all([batch, work_order])
        db.commit()
        batch_id, work_order_id = batch.id, work_order.id

    payload = {
        "work_order_id": work_order_id, "input_quantity": 1,
        "cut_pieces": 0, "passed_pieces": 0,
        "materials": [{
            "stock_batch_id": batch_id, "quantity": 1, "unit": "kg",
            "details": {"cut_pieces": 2_147_483_648},
        }],
    }
    assert CuttingRecordIn.model_validate(payload).materials[0].details.cut_pieces == 2_147_483_648
    before = _cutting_create_state()
    response = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert response.status_code == 422, response.text
    assert "cut_pieces" in response.text
    assert _cutting_create_state() == before


def test_cutting_json_cut_pieces_storage_boundary():
    production._validate_cutting_usage_details_bounds({"cut_pieces": 2_147_483_647})
    with pytest.raises(HTTPException, match="cut_pieces") as exc_info:
        production._validate_cutting_usage_details_bounds({"cut_pieces": 2_147_483_648})
    assert exc_info.value.status_code == 422


def test_oversized_cutting_usage_edit_rejects_before_any_write(monkeypatch):
    details = {
        "layer_material_kg": 1.0,
        "beika_kg": 0.0,
        "material_rolls_used": 0.0,
        "layup_operator_name": "Operator",
        "legacy_extension": "x" * production._MAX_CUTTING_USAGE_DETAILS_BYTES,
    }
    usage = SimpleNamespace(stock_batch_id=7, details=details, position=1)
    record = SimpleNamespace(
        id=55,
        work_order_id=9,
        layer_material_kg=1.0,
        beika_kg=0.0,
        material_rolls_used=0.0,
        layup_operator_name="Operator",
        notes=None,
        materials=[usage],
    )
    work_order = SimpleNamespace(id=9, operation="cutting")
    query = Mock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = record
    db = Mock()
    db.query.return_value = query
    db.get.return_value = work_order
    monkeypatch.setattr("app.services.factory_scope.require_work_order_factory_access", lambda *_args: None)
    monkeypatch.setattr(production, "log_action", Mock())

    with pytest.raises(HTTPException, match="16 KiB") as exc_info:
        production.update_cutting_record_details(
            55,
            production.CuttingRecordDetailsUpdateIn(layer_material_kg=2.0),
            db,
            SimpleNamespace(id=1),
        )

    assert exc_info.value.status_code == 422
    assert usage.details == details
    db.commit.assert_not_called()


def test_exact_unchanged_oversized_legacy_cutting_details_pass_through():
    legacy = {"old_extension": "x" * production._MAX_CUTTING_USAGE_DETAILS_BYTES}

    production._validate_cutting_usage_details_bounds(legacy, existing=legacy)


def test_changed_deep_cutting_details_reject_before_serialization():
    legacy = None
    changed = value = {}
    for _ in range(production._MAX_CUTTING_USAGE_DETAILS_DEPTH + 1):
        child = {}
        if legacy is None:
            legacy = child
        value["nested"] = child
        value = child

    with pytest.raises(HTTPException, match="nesting depth") as exc_info:
        production._validate_cutting_usage_details_bounds(changed, existing=legacy)

    assert exc_info.value.status_code == 422
