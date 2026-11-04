"""Reservation readiness stays distinct from persisted reservation lifecycle."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.material_reservation_output import MaterialReservationPlanOut
from app.libs.enums.inventory import ReservationPlanRowStatus, ReservationPlanStatus
from app.models import inventory_service


@pytest.mark.parametrize(
    ("required", "reserved", "stock", "row_status", "complete"),
    [(5, 5, 0, "ready", True), (5, 0, 2, "shortage", False),
     (5, 0, 5, "partial", False)],
)
def test_plan_statuses_and_json(monkeypatch, required, reserved, stock, row_status, complete):
    po = SimpleNamespace(id=1, model_id=2, production_no="PO-1", order_no=None,
                         sales_order_id=None, planned_quantity=1)
    db = Mock()
    db.get.return_value = po
    monkeypatch.setattr(inventory_service, "_model_label_fields", lambda *a: (None, None))
    monkeypatch.setattr(inventory_service, "_reservation_coverage_maps", lambda *a: ({(3, "kg"): reserved}, {}))
    row = {"item_id": 3, "item_sku": "S", "item_name": "Material", "category": "fabric",
           "reservation_type": "material", "unit": "kg", "required_quantity": required}
    monkeypatch.setattr(inventory_service, "_bom_requirement_rows", lambda *a: [row])
    monkeypatch.setattr(inventory_service, "_reservation_plan_stock_context", lambda *a: {
        "current_by_item": {3: stock}, "reserved_by_item": {}, "reserved_by_batch": {},
        "candidates_by_item": {}, "candidate_ids": set(), "batches_by_id": {}})
    monkeypatch.setattr(inventory_service, "_suggest_batches_for_requirement", lambda **kw: [])
    plan = inventory_service.reservation_plan_for_production_order(db, 1)
    assert plan["status"] is ReservationPlanStatus(row_status)
    assert plan["rows"][0]["status"] is ReservationPlanRowStatus(row_status)
    assert plan["is_complete"] is complete
    wire = json.loads(MaterialReservationPlanOut.model_validate(plan).model_dump_json())
    assert wire["status"] == wire["rows"][0]["status"] == row_status
    assert json.loads(json.dumps(plan))["status"] == row_status
    plan["rows"][0]["status"] = "no_bom"
    with pytest.raises(ValidationError):
        MaterialReservationPlanOut.model_validate(plan)


def test_no_bom_is_complete_and_serializes(monkeypatch):
    po = SimpleNamespace(id=1, model_id=2, production_no="PO-1", order_no=None,
                         sales_order_id=None, planned_quantity=1)
    db = Mock()
    db.get.return_value = po
    monkeypatch.setattr(inventory_service, "_model_label_fields", lambda *a: (None, None))
    monkeypatch.setattr(inventory_service, "_reservation_coverage_maps", lambda *a: ({}, {}))
    monkeypatch.setattr(inventory_service, "_bom_requirement_rows", lambda *a: [])
    monkeypatch.setattr(inventory_service, "_reservation_plan_stock_context", lambda *a: {
        "current_by_item": {}, "reserved_by_item": {}, "reserved_by_batch": {},
        "candidates_by_item": {}, "candidate_ids": set(), "batches_by_id": {}})
    plan = inventory_service.reservation_plan_for_production_order(db, 1)
    assert plan["status"] is ReservationPlanStatus.NO_BOM
    assert plan["is_complete"] is True
    wire = json.loads(MaterialReservationPlanOut.model_validate(plan).model_dump_json())
    assert wire["status"] == "no_bom" and wire["rows"] == []
    plan["status"] = "unknown"
    with pytest.raises(ValidationError):
        MaterialReservationPlanOut.model_validate(plan)
