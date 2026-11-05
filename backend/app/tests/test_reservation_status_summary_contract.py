"""Reservation status summary and internal stock-context contracts."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.material_reservation_output import MaterialReservationStatusOut
from app.models import inventory_service
from app.schemas import StockBatch
from app.tests.test_reservation_plan_query_growth import (
    _base_rows,
    _new_batch,
    _new_item,
    postgres_session_factory as postgres_session_factory,  # noqa: F401
)


@pytest.mark.parametrize("populated", [False, True])
def test_status_summary_producer_and_nested_wire_preserve_numbers(monkeypatch, populated):
    quantities = 1.25 if populated else 0
    plan_summary = {
        "required_quantity": quantities, "already_reserved_quantity": quantities,
        "remaining_to_reserve": quantities, "shortage": quantities,
        "line_count": int(populated), "ready_line_count": 0, "shortage_line_count": 0,
    }
    plan = {
        "production_order_id": 1, "production_no": "PO-1", "model_id": 1,
        "planned_quantity": 1, "status": "no_bom", "is_complete": True,
        "summary": plan_summary, "rows": [],
    }
    monkeypatch.setattr(inventory_service, "reservation_plan_for_production_order", lambda *_: plan)
    row = SimpleNamespace(status="reserved", reserved_quantity=3.0,
                          consumed_quantity=0.5, released_quantity=0.25)
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [row] if populated else []
    result = inventory_service.material_reservation_status_for_production_order(db, 1)
    expected = {
        **plan_summary,
        "active_reserved_quantity": 2.25 if populated else 0,
        "consumed_quantity": 0.5 if populated else 0,
        "released_quantity": 0.25 if populated else 0,
        "reservation_count": int(populated),
    }
    assert result["summary"] == expected
    # Reservation ORM serialization is covered elsewhere; isolate nested summaries here.
    result["reservations"] = []
    wire = json.loads(MaterialReservationStatusOut.model_validate(result).model_dump_json())
    assert list(wire["summary"]) == list(expected)
    assert wire["summary"] == expected
    assert all(type(wire["summary"][k]) is type(v) for k, v in expected.items())
    for key in expected:
        incomplete = dict(result, summary={k: v for k, v in expected.items() if k != key})
        with pytest.raises(ValidationError):
            MaterialReservationStatusOut.model_validate(incomplete)
    extra = dict(result, summary={**expected, "future_value": 7})
    assert "future_value" not in MaterialReservationStatusOut.model_validate(extra).model_dump()["summary"]


def test_status_summary_openapi_is_explicit(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert schemas["MaterialReservationStatusOut"]["properties"]["summary"]["$ref"] == "#/components/schemas/ReservationStatusSummaryOut"
    summary = schemas["ReservationStatusSummaryOut"]
    assert set(summary["required"]) == {
        "required_quantity", "already_reserved_quantity", "remaining_to_reserve", "shortage",
        "line_count", "ready_line_count", "shortage_line_count", "active_reserved_quantity",
        "consumed_quantity", "released_quantity", "reservation_count",
    }
    for key in ("active_reserved_quantity", "consumed_quantity", "released_quantity"):
        assert {branch["type"] for branch in summary["properties"][key]["anyOf"]} == {"integer", "number"}
    assert summary["properties"]["reservation_count"]["type"] == "integer"


def test_stock_context_empty_and_populated_postgres(postgres_session_factory):  # noqa: F811
    marker = uuid4().hex[:8]
    catalog = _base_rows(postgres_session_factory, marker)
    with postgres_session_factory.begin() as db:
        item = _new_item(db, marker, 0)
        batch = _new_batch(db, item_id=item.id, warehouse_id=catalog["warehouse_id"],
                           marker=marker, index=0, quantity=5, unit="kg", day_offset=0)
        item_id, batch_id = item.id, batch.id
    with postgres_session_factory() as db:
        empty = inventory_service._reservation_plan_stock_context(db, [])
        assert empty == {key: {} for key in (
            "current_by_item", "reserved_by_item", "reserved_by_batch", "candidates_by_item",
            "candidate_ids", "batches_by_id",
        )}
        context = inventory_service._reservation_plan_stock_context(
            db, [{"item_id": item_id, "stock_batch_id": batch_id}]
        )
        assert context["current_by_item"][item_id] == 5.0
        assert context["candidate_ids"][batch_id].id == batch_id
        assert isinstance(context["candidate_ids"][batch_id], StockBatch)
        assert [batch.id for batch in context["candidates_by_item"][item_id]] == [batch_id]
        assert context["batches_by_id"][batch_id].id == batch_id
