"""Reservation readiness stays distinct from persisted reservation lifecycle."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.material_reservation_output import MaterialReservationPlanOut, ReservationPlanSummaryOut
from app.libs.enums.inventory import ReservationPlanRowStatus, ReservationPlanStatus
from app.models import inventory_service


def test_summary_requires_complete_contract_and_preserves_json_number_types():
    values = {
        "required_quantity": 0, "already_reserved_quantity": 2.5,
        "remaining_to_reserve": 1.0, "shortage": 0.0,
        "line_count": 2, "ready_line_count": 1, "shortage_line_count": 0,
    }
    wire = json.loads(ReservationPlanSummaryOut.model_validate(values).model_dump_json())
    assert list(wire) == list(values)
    assert wire == values
    assert all(type(wire[key]) is type(value) for key, value in values.items())
    for key in values:
        with pytest.raises(ValidationError):
            ReservationPlanSummaryOut.model_validate({k: v for k, v in values.items() if k != key})


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
    assert wire["summary"] == plan["summary"]
    assert list(wire["summary"]) == list(plan["summary"])
    for key in ("required_quantity", "already_reserved_quantity", "remaining_to_reserve", "shortage"):
        assert type(wire["summary"][key]) is type(plan["summary"][key])
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
    assert all(type(plan["summary"][key]) is int for key in (
        "required_quantity", "already_reserved_quantity", "remaining_to_reserve", "shortage"
    ))
    wire = json.loads(MaterialReservationPlanOut.model_validate(plan).model_dump_json())
    assert wire["status"] == "no_bom" and wire["rows"] == []
    assert wire["summary"] == plan["summary"]
    assert list(wire["summary"]) == list(plan["summary"])
    assert all(type(wire["summary"][key]) is int for key in plan["summary"])
    plan["status"] = "unknown"
    with pytest.raises(ValidationError):
        MaterialReservationPlanOut.model_validate(plan)


def test_openapi_exposes_distinct_readiness_vocabularies(client):
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    plan_status = schemas["MaterialReservationPlanOut"]["properties"]["status"]
    row_status = schemas["MaterialReservationPlanRow"]["properties"]["status"]
    assert plan_status["$ref"] == "#/components/schemas/ReservationPlanStatus"
    assert row_status["$ref"] == "#/components/schemas/ReservationPlanRowStatus"
    assert schemas["MaterialReservationPlanOut"]["properties"]["summary"]["$ref"] == "#/components/schemas/ReservationPlanSummaryOut"
    summary = schemas["ReservationPlanSummaryOut"]
    assert set(summary["required"]) == {
        "required_quantity", "already_reserved_quantity", "remaining_to_reserve", "shortage",
        "line_count", "ready_line_count", "shortage_line_count",
    }
    for name in ("required_quantity", "already_reserved_quantity", "remaining_to_reserve", "shortage"):
        assert {branch["type"] for branch in summary["properties"][name]["anyOf"]} == {"integer", "number"}
    for name in ("line_count", "ready_line_count", "shortage_line_count"):
        assert summary["properties"][name]["type"] == "integer"
    assert set(schemas["ReservationPlanStatus"]["enum"]) == {"ready", "shortage", "partial", "no_bom"}
    assert set(schemas["ReservationPlanRowStatus"]["enum"]) == {"ready", "shortage", "partial"}
    response = document["paths"]["/api/inventory/reservations/plan"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/MaterialReservationPlanOut"


def test_inventory_plan_route_serializes_mixed_readiness_and_counts(client, auth_headers, monkeypatch):
    from app.models.inventory import reservations_service

    po = SimpleNamespace(id=1, model_id=2, production_no="PO-1", order_no=None,
                         sales_order_id=None, planned_quantity=1)
    db = Mock()
    db.get.return_value = po
    monkeypatch.setattr(inventory_service, "_model_label_fields", lambda *a: (None, None))
    monkeypatch.setattr(inventory_service, "_reservation_coverage_maps", lambda *a: ({(3, "kg"): 5}, {}))
    rows = [
        {"item_id": item_id, "item_sku": str(item_id), "item_name": "Material",
         "category": "fabric", "reservation_type": "material", "unit": "kg", "required_quantity": 5}
        for item_id in (3, 4, 5)
    ]
    monkeypatch.setattr(inventory_service, "_bom_requirement_rows", lambda *a: rows)
    monkeypatch.setattr(inventory_service, "_reservation_plan_stock_context", lambda *a: {
        "current_by_item": {3: 0, 4: 5, 5: 2}, "reserved_by_item": {}, "reserved_by_batch": {},
        "candidates_by_item": {}, "candidate_ids": set(), "batches_by_id": {}})
    monkeypatch.setattr(inventory_service, "_suggest_batches_for_requirement", lambda **kw: [])
    monkeypatch.setattr(reservations_service, "reservation_plan_for_production_order",
                        lambda _db, order_id, categories=None: inventory_service.reservation_plan_for_production_order(db, order_id, categories))
    response = client.get("/api/inventory/reservations/plan?production_order_id=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert [row["status"] for row in plan["rows"]] == ["ready", "partial", "shortage"]
    assert plan["status"] == "shortage"
    assert plan["is_complete"] is False
    assert plan["summary"]["line_count"] == 3
    assert plan["summary"]["ready_line_count"] == 1
    assert plan["summary"]["shortage_line_count"] == 1
    assert plan["summary"]["remaining_to_reserve"] == 10
    assert plan["summary"]["shortage"] == 3


def test_internal_suggestion_and_composition_keep_raw_values():
    received = datetime(2026, 1, 2, tzinfo=timezone.utc)
    batch = SimpleNamespace(id=7, item_id=3, unit="kg", quantity=2,
                            batch_no="B-7", warehouse_id=4, received_date=received)
    suggestion = inventory_service._suggest_batches_for_requirement(
        candidates=[batch], candidate_ids={7: batch}, reserved_by_batch={7: 0.5},
        item_id=3, unit="kg", quantity=1.0,
    )[0]
    assert suggestion["received_date"] is received
    assert suggestion["suggested_quantity"] == 1.0
    assert type(suggestion["current_quantity"]) is float
    item = SimpleNamespace(composition_json=[{"name": " Cotton ", "percentage": "75"}])
    composition = inventory_service._item_composition(item)
    assert composition == [{"name": "Cotton", "percentage": 75.0}]
    assert isinstance(composition[0], dict)
