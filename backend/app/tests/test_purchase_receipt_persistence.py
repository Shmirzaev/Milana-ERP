"""Purchasing receipt writes cross into their schema-owning domains."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import get_type_hints

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import object_session

from app.db import session as session_module
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.enums.purchasing import PurchaseOrderStatus
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderOut, PurchaseOrderReceiptOut
from app.libs.types.inventory import PurchaseOrderStockReceiptCommand
from app.models import purchasing_service
from app.models.inventory import stock_service as inventory_stock
from app.schemas import (
    AuditLog,
    IdempotencyRecord,
    PurchaseOrder,
    PurchaseOrderLine,
    StockBatch,
    StockMovement,
    User,
)
from app.schemas.purchasing import purchase_order_persistence
from app.tests.test_purchase_receipt_idempotency import (
    receipt_order as receipt_order,
    receipt_state,
)


@pytest.mark.parametrize("status", list(PurchaseOrderStatus))
def test_purchase_order_receipt_output_uses_canonical_status_and_keeps_wire_value(status):
    value = {
        "id": 1,
        "po_no": "PO-TYPED-STATUS",
        "status": status.value,
        "created_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    }
    result = PurchaseOrderReceiptOut.model_validate(value)
    assert result.status is status
    assert result.model_dump(mode="json")["status"] == status.value
    assert get_type_hints(PurchaseOrderReceiptOut)["status"] is PurchaseOrderStatus
    assert PurchaseOrderReceiptOut.model_json_schema()["properties"]["status"]["$ref"].endswith(
        "/PurchaseOrderStatus"
    )


def test_purchase_order_receipt_output_rejects_unknown_historical_status_without_coercion():
    value = {
        "id": 1,
        "po_no": "PO-HISTORICAL-STATUS",
        "status": "historical_custom",
        "created_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    }
    with pytest.raises(ValidationError):
        PurchaseOrderReceiptOut.model_validate(value)
    assert PurchaseOrderOut.model_validate(value).status == "historical_custom"


def test_only_receipt_route_uses_typed_purchase_order_status_response():
    from app.api.routes.purchasing import router
    from app.main import app

    routes = {(route.path, method): route for route in router.routes for method in route.methods}
    assert routes[("/purchasing/orders/{order_id}/receive", "POST")].response_model is PurchaseOrderReceiptOut
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["PurchaseOrderReceiptOut"]["properties"]["status"] == {
        "$ref": "#/components/schemas/PurchaseOrderStatus"
    }
    assert set(schemas["PurchaseOrderStatus"]["enum"]) == {status.value for status in PurchaseOrderStatus}


def test_purchase_receipt_uses_public_inventory_and_purchasing_writers_same_session(
    receipt_order, monkeypatch,
):
    db = session_module.SessionLocal()
    calls = {"inventory": [], "line": [], "header": []}
    original_inventory = inventory_stock.record_purchase_order_stock_receipt
    original_line = purchase_order_persistence.apply_purchase_order_line_receipt
    original_header = purchase_order_persistence.apply_purchase_order_receipt_status

    def inventory_writer(session, *, command):
        assert session is db
        calls["inventory"].append(command)
        result = original_inventory(session, command=command)
        calls["result"] = result
        return result

    def line_writer(line, **kwargs):
        assert object_session(line) is db
        calls["line"].append((line, kwargs))
        return original_line(line, **kwargs)

    def header_writer(order, **kwargs):
        assert object_session(order) is db
        calls["header"].append((order, kwargs))
        return original_header(order, **kwargs)

    monkeypatch.setattr(inventory_stock, "record_purchase_order_stock_receipt", inventory_writer)
    monkeypatch.setattr(purchase_order_persistence, "apply_purchase_order_line_receipt", line_writer)
    monkeypatch.setattr(purchase_order_persistence, "apply_purchase_order_receipt_status", header_writer)
    try:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        order = purchasing_service.receive_purchase_order(
            db,
            order_id=receipt_order["order_id"],
            data=deepcopy(receipt_order["payload"]),
            current=actor,
        )

        assert len(calls["inventory"]) == len(calls["line"]) == len(calls["header"]) == 1
        command = calls["inventory"][0]
        assert get_type_hints(PurchaseOrderStockReceiptCommand)["qc_status"] is StockBatchQcStatus
        assert command.qc_status is StockBatchQcStatus.PASSED
        assert command.internal_batch_no == receipt_order["po_no"]
        assert command.purchase_order_line_id == receipt_order["line_id"]
        assert command.created_by == actor.id
        assert calls["result"].batch_id > 0
        assert calls["result"].batch_no == receipt_order["payload"]["lines"][0]["batch_no"]
        assert calls["result"].internal_batch_no == receipt_order["po_no"]
        assert calls["line"][0][1] == {
            "received_quantity": 5.0,
            "unit_cost": None,
            "warehouse_id": None,
        }
        assert calls["header"][0][1]["status"].value == "partially_received"

        batch = db.query(StockBatch).filter_by(internal_batch_no=receipt_order["po_no"]).one()
        movement = db.query(StockMovement).filter_by(
            reference_type="PurchaseOrderLine", reference_id=receipt_order["line_id"],
        ).one()
        line = db.get(PurchaseOrderLine, receipt_order["line_id"])
        assert movement.batch_id == batch.id
        assert movement.created_by == actor.id
        assert movement.to_warehouse_id == receipt_order["warehouse_id"]
        assert line.received_quantity == 5
        assert order.status == "partially_received"
        audit = db.query(AuditLog).filter_by(
            entity_id=batch.id, entity_type="StockBatch", action="receive",
        ).one()
        assert audit.new_value_json["batch_no"] == batch.batch_no
        assert audit.new_value_json["internal_batch_no"] == batch.internal_batch_no
        with session_module.SessionLocal() as observer:
            assert observer.query(StockBatch).filter_by(internal_batch_no=receipt_order["po_no"]).count() == 0
            assert observer.query(StockMovement).filter_by(
                reference_type="PurchaseOrderLine", reference_id=receipt_order["line_id"],
            ).count() == 0
            assert observer.get(PurchaseOrderLine, receipt_order["line_id"]).received_quantity == 0
            assert observer.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch.id).count() == 0
    finally:
        db.rollback()
        db.close()


def test_unsupported_later_core_qc_fails_before_any_receipt_write_then_retry_succeeds(
    receipt_order,
):
    """Direct core inputs preflight fixed-vocabulary values before staging rows."""
    before = receipt_state(receipt_order)
    db = session_module.SessionLocal()
    try:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        valid_line = deepcopy(receipt_order["payload"]["lines"][0])
        invalid_line = {**deepcopy(valid_line), "batch_no": "INVALID-LATER-QC"}
        invalid_line["qc_status"] = "unsupported-internal-qc"
        invalid_data = {"lines": [valid_line, invalid_line]}

        with pytest.raises(ValueError):
            purchasing_service.receive_purchase_order(
                db,
                order_id=receipt_order["order_id"],
                data=invalid_data,
                current=actor,
            )
        # Inspect this transaction before rollback: a later-line validation
        # failure must not leave earlier-line rows or mutations staged.
        assert db.query(StockBatch).filter_by(internal_batch_no=receipt_order["po_no"]).count() == 0
        assert db.query(StockMovement).filter_by(
            reference_type="PurchaseOrderLine", reference_id=receipt_order["line_id"],
        ).count() == 0
        assert db.get(PurchaseOrderLine, receipt_order["line_id"]).received_quantity == 0
        assert db.get(PurchaseOrder, receipt_order["order_id"]).status == "sent"
        assert db.query(AuditLog).filter(
            (AuditLog.entity_type == "PurchaseOrderLine")
            & (AuditLog.entity_id == receipt_order["line_id"])
        ).count() == 0
        assert db.query(AuditLog).filter(
            (AuditLog.entity_type == "PurchaseOrder")
            & (AuditLog.entity_id == receipt_order["order_id"])
        ).count() == 0
        assert db.query(IdempotencyRecord).count() == before[5]
        db.rollback()
        assert receipt_state(receipt_order) == before

        result = purchasing_service.receive_purchase_order(
            db,
            order_id=receipt_order["order_id"],
            data={"lines": [valid_line]},
            current=actor,
        )
        db.commit()
        assert result.id == receipt_order["order_id"]
        after = receipt_state(receipt_order)
        assert after[:4] == (5, "partially_received", 1, 1)
        assert after[4] == before[4] + 3
        assert after[5] == before[5]
    finally:
        db.rollback()
        db.close()
